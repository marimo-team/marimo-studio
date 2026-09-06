#!/usr/bin/env bash
set -euo pipefail

record() {
    printf 'validated=%s\n' "$1" >> "$GITHUB_OUTPUT"
    {
        printf '### Pull request validation\n\n'
        printf '%s\n' "$2"
    } >> "$GITHUB_STEP_SUMMARY"
    exit 0
}

if [[ "$GITHUB_EVENT_NAME" != "push" || "$GITHUB_REF" != "refs/heads/main" ]]; then
    record false "The pull request run owns validation for this event."
fi

if ! pulls="$(gh api "repos/$GITHUB_REPOSITORY/commits/$GITHUB_SHA/pulls")"; then
    record false "The associated pull request could not be resolved. The main workflow will run."
fi
matching_pulls="$(
    jq --arg branch "$GITHUB_REF_NAME" --arg commit "$GITHUB_SHA" \
        '[.[] | select(
          .merged_at != null and
          .merge_commit_sha == $commit and
          .base.ref == $branch
        )]' \
        <<< "$pulls"
)"
if [[ "$(jq 'length' <<< "$matching_pulls")" != "1" ]]; then
    record false "The main commit has no unique merged pull request. The main workflow will run."
fi

pull_number="$(jq -r '.[0].number' <<< "$matching_pulls")"
head_label="$(jq -r '.[0].head.label' <<< "$matching_pulls")"
head_sha="$(jq -r '.[0].head.sha' <<< "$matching_pulls")"
head_ref="$(jq -r '.[0].head.ref' <<< "$matching_pulls")"
head_repository="$(jq -r '.[0].head.repo.full_name' <<< "$matching_pulls")"
if [[ "$head_repository" != "$GITHUB_REPOSITORY" ]]; then
    record false "Pull request #$pull_number comes from another repository. The main workflow will run."
fi
if ! head_pulls="$(
    gh api --method GET \
        "repos/$GITHUB_REPOSITORY/pulls" \
        -f state=all \
        -f head="$head_label" \
        -f per_page=100
)"; then
    record false "Pull request #$pull_number head ownership could not be read. The main workflow will run."
fi
matching_head_pulls="$(
    jq --argjson number "$pull_number" --arg head_sha "$head_sha" \
        '[.[] | select(.number == $number and .head.sha == $head_sha)]' \
        <<< "$head_pulls"
)"
if [[ "$(jq 'length' <<< "$matching_head_pulls")" != "1" || \
      "$(jq --arg head_sha "$head_sha" '[.[] | select(.head.sha == $head_sha)] | length' \
        <<< "$head_pulls")" != "1" ]]; then
    record false "Pull request #$pull_number does not uniquely own its head commit. The main workflow will run."
fi
if ! merged_tree="$(git rev-parse "$GITHUB_SHA^{tree}")"; then
    record false "The merged Git tree could not be read. The main workflow will run."
fi
if ! parent_sha="$(git rev-parse "$GITHUB_SHA^")"; then
    record false "The previous main commit could not be read. The main workflow will run."
fi
if ! base_runs="$(
    gh api --method GET \
        "repos/$GITHUB_REPOSITORY/actions/workflows/$VALIDATION_WORKFLOW/runs" \
        -f branch="$GITHUB_REF_NAME" \
        -f event=push \
        -f head_sha="$parent_sha" \
        -f per_page=10
)"; then
    record false "The previous main validation could not be read. The main workflow will run."
fi
latest_base="$(
    jq \
        --arg branch "$GITHUB_REF_NAME" \
        --arg repository "$GITHUB_REPOSITORY" \
        '[.workflow_runs[] | select(
          .head_branch == $branch and
          .head_repository.full_name == $repository
        )] | sort_by(.created_at, .run_attempt) | reverse | .[0] // null' \
        <<< "$base_runs"
)"
if [[ "$(jq -r '.status // ""' <<< "$latest_base")" != "completed" || \
      "$(jq -r '.conclusion // ""' <<< "$latest_base")" != "success" ]]; then
    record false "The previous main commit has no successful $VALIDATION_WORKFLOW run. The main workflow will run."
fi

if ! runs="$(
    gh api --method GET \
        "repos/$GITHUB_REPOSITORY/actions/workflows/$VALIDATION_WORKFLOW/runs" \
        -f event=pull_request \
        -f head_sha="$head_sha" \
        -f per_page=10
)"; then
    record false "Pull request #$pull_number workflow evidence could not be read. The main workflow will run."
fi
latest="$(
    jq \
        --arg head_ref "$head_ref" \
        --arg head_repository "$head_repository" \
        '[.workflow_runs[] | select(
          .head_branch == $head_ref and
          .head_repository.full_name == $head_repository
        )] | sort_by(.created_at, .run_attempt) | reverse | .[0] // null' \
        <<< "$runs"
)"
if [[ "$(jq -r '.status // ""' <<< "$latest")" != "completed" || \
      "$(jq -r '.conclusion // ""' <<< "$latest")" != "success" ]]; then
    record false "Pull request #$pull_number has no successful $VALIDATION_WORKFLOW run. The main workflow will run."
fi

run_id="$(jq -r '.id' <<< "$latest")"
if ! artifacts="$(
    gh api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/artifacts"
)"; then
    record false "Pull request #$pull_number tested-tree evidence could not be read. The main workflow will run."
fi
matching_artifacts="$(
    jq '[.artifacts[] | select(
      .name == "pr-validation-tree" and
      .expired == false and
      .size_in_bytes > 0 and
      .size_in_bytes <= 1024
    )]' \
        <<< "$artifacts"
)"
if [[ "$(jq 'length' <<< "$matching_artifacts")" != "1" ]]; then
    record false "Pull request #$pull_number has no unique tested-tree artifact. The main workflow will run."
fi

artifact_id="$(jq -r '.[0].id' <<< "$matching_artifacts")"
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT
archive="$temporary_directory/tested-tree.zip"
if ! gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" > "$archive"; then
    record false "Pull request #$pull_number tested-tree evidence could not be downloaded. The main workflow will run."
fi
if ! tested_tree="$(unzip -p "$archive" pr-validation-tree)"; then
    record false "Pull request #$pull_number tested-tree evidence could not be extracted. The main workflow will run."
fi
if [[ ! "$tested_tree" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
    record false "Pull request #$pull_number tested-tree evidence is invalid. The main workflow will run."
fi
if [[ "$tested_tree" != "$merged_tree" ]]; then
    record false "Pull request #$pull_number tested a different Git tree. The main workflow will run."
fi

run_url="$(jq -r '.html_url' <<< "$latest")"
record true "Pull request #$pull_number passed $VALIDATION_WORKFLOW for Git tree \`$merged_tree\`: $run_url"
