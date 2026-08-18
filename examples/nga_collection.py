# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo-studio",
#   "numpy",
#   "polars",
#   "pyobservablejs",
# ]
#
# [tool.marimo-studio]
# default = "corpus"
# preserve_session = false
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# corpus_controls = {ref = "cell:v1:1e7b1299b526e7923a360edddeec9f8d7420675ca1ba53bec9cdf29ee7e276e2:1e7b1299b526e7923a360edddeec9f8d7420675ca1ba53bec9cdf29ee7e276e2:0"}
# corpus_index = {ref = "cell:v1:2fb589cc8ede7aceb9f96c399816699d4d5d9bda13b43131fa11c601d06f7e80:2fb589cc8ede7aceb9f96c399816699d4d5d9bda13b43131fa11c601d06f7e80:0"}
# corpus_filter_chart = {ref = "cell:v1:56890f3d9ed67d57e6aa28d6a6be5a6e746eb81bc403c0ae73eccb87f0ce8b2a:56890f3d9ed67d57e6aa28d6a6be5a6e746eb81bc403c0ae73eccb87f0ce8b2a:0"}
# study_controls = {ref = "cell:v1:8b02c89d51b7852cba5e8d47ec911aaa04ac7acedc9b7c3396304770008232c0:8b02c89d51b7852cba5e8d47ec911aaa04ac7acedc9b7c3396304770008232c0:0"}
# study_gallery = {ref = "cell:v1:bf7065e0cb4407b04ed39350dc67960716a84436d94ac213959c448bea9c7684:bf7065e0cb4407b04ed39350dc67960716a84436d94ac213959c448bea9c7684:0"}
# selection_status = {ref = "cell:v1:286cbc5de419e150bea06e30762e268d8aabe9a4bea9eda504309b5a6782ee27:de05ec8ddbf4fe275810c002d7dcfb9125fd1b9646746460ab2885f5499e7d31:0"}
# packet_preview = {ref = "cell:v1:a628d3557c21e94f77eab871a78c9d99f70c38a9616e46f2a7619e644dc1f616:a628d3557c21e94f77eab871a78c9d99f70c38a9616e46f2a7619e644dc1f616:0"}
# packet_table = {ref = "cell:v1:446d594f529af70408d73eaf7049f31bcb36ad1f28dc46cbe55a31dc33701b04:446d594f529af70408d73eaf7049f31bcb36ad1f28dc46cbe55a31dc33701b04:0"}
# packet_download = {ref = "cell:v1:e7a3a021a379707ab44ece668c53b832a320363fb90361d5ab5ec81a9a3939ae:e7a3a021a379707ab44ece668c53b832a320363fb90361d5ab5ec81a9a3939ae:0"}
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Index of American Design: corpus review and research packet

    This notebook prepares a focused research set from the National Gallery of
    Art's open collection data. It establishes an object-grain model, locates
    the Index of American Design in the collection timeline, supports visual
    review, and packages six works with enough provenance for handoff.
    """)
    return


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    _revision = "e19fc9a6bf8167630be458f745dfff915fbe06ba"
    _base_url = (
        "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/"
        f"{_revision}/data"
    )
    research_config = {
        "dataset_revision": _revision,
        "dataset_base_url": _base_url,
        "creator_role_type": "artist",
        "unknown_creator": "Unattributed",
        "corpus_classification": "Index of American Design",
        "gallery_page_size": 72,
        "packet_limit": 6,
    }
    return (research_config,)


@app.cell(hide_code=True)
def _(mo, research_config):
    mo.md(f"""
    ## Source tables and grain

    The [NGA Open Data Program](https://www.nga.gov/open-access-images/open-data.html)
    publishes collection records under CC0. This run pins source revision
    `{research_config["dataset_revision"][:12]}` so a saved packet can be traced
    to the exact input.

    Four tables carry different grains:

    - `objects.csv` has one row per collection object.
    - `objects_constituents.csv` has one row per object and constituent role.
    - `constituents.csv` describes people and organizations.
    - `published_images.csv` has one row per published image.

    Keeping those grains explicit prevents objects with several creators or
    images from being counted several times. The object table stays complete
    for historical discovery. Relation, constituent, and image rows are then
    narrowed to the configured corpus after their source counts are recorded.
    """)
    return


@app.cell
def _(research_config):
    import polars as _pl

    def _load_source_tables():
        _base_url = research_config["dataset_base_url"]
        _objects = _pl.read_csv(
            f"{_base_url}/objects.csv",
            infer_schema_length=10_000,
        ).select(
            "objectid",
            "accessionnum",
            "title",
            "displaydate",
            "beginyear",
            "endyear",
            "medium",
            "attribution",
            "creditline",
            "classification",
            "subclassification",
            "visualbrowserclassification",
        )
        _collection_objects = _objects.select(
            "objectid",
            _pl.col("beginyear").alias("start_year"),
            _pl.col("classification").fill_null("Unclassified"),
            _pl.col("visualbrowserclassification").fill_null("Other"),
        )
        _index_source_objects = _objects.filter(
            _pl.col("classification") == research_config["corpus_classification"]
        )
        return (
            _collection_objects,
            _index_source_objects,
            {"source": _objects.height, "working": _objects.height},
        )

    collection_objects, index_source_objects, object_source_counts = (
        _load_source_tables()
    )
    return collection_objects, index_source_objects, object_source_counts


@app.cell
def _(
    creator_source_counts,
    image_source_counts,
    mo,
    object_source_counts,
):
    source_rows = [
        {
            "Table": "objects",
            "Grain": "collection object",
            "Source rows": f"{object_source_counts['source']:,}",
            "Working rows": f"{object_source_counts['working']:,}",
        },
        {
            "Table": "objects_constituents",
            "Grain": "object and constituent role",
            "Source rows": f"{creator_source_counts['relations_source']:,}",
            "Working rows": f"{creator_source_counts['relations_working']:,}",
        },
        {
            "Table": "constituents",
            "Grain": "person or organization",
            "Source rows": f"{creator_source_counts['constituents_source']:,}",
            "Working rows": f"{creator_source_counts['constituents_working']:,}",
        },
        {
            "Table": "published_images",
            "Grain": "published image",
            "Source rows": f"{image_source_counts['source']:,}",
            "Working rows": f"{image_source_counts['working']:,}",
        },
    ]
    source_table = mo.ui.table(
        source_rows,
        selection=None,
        pagination=False,
        show_column_summaries=False,
        show_data_types=False,
        show_download=False,
        show_search=False,
    )
    source_table
    return (source_table,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Attribution policy

    The relation table distinguishes a broad `roletype` from a specific `role`.
    A painter, engraver, designer, or related artist can all belong to the
    `artist` role type. The
    [NGA data dictionary](https://github.com/NationalGalleryOfArt/opendata/blob/e19fc9a6bf8167630be458f745dfff915fbe06ba/documentation/Data%20Dictionary.txt)
    defines `displayorder` as source sequence. The model therefore names its
    first relation `first_artist_name` and keeps the object's `attribution` as
    the default display label.

    Use the policy control below to compare the museum's display-ready
    attribution with the first related artist in source display order. Every
    gallery card and packet record recomputes while retaining both source
    representations.
    """)
    return


@app.cell
def _(mo):
    attribution_policy_control = mo.ui.dropdown(
        options={
            "Museum display attribution": "source",
            "First artist relation": "first_relation",
        },
        value="Museum display attribution",
        label="Display attribution policy",
        full_width=True,
    )
    attribution_policy_control
    return (attribution_policy_control,)


@app.cell
def _(attribution_policy_control):
    attribution_policy = attribution_policy_control.value
    return (attribution_policy,)


@app.cell
def _(index_source_objects, research_config):
    import polars as _pl

    def _load_creator_relations():
        _base_url = research_config["dataset_base_url"]
        _all_relations = _pl.read_csv(
            f"{_base_url}/objects_constituents.csv",
            quote_char='"',
            infer_schema_length=None,
        ).select(
            "objectid",
            "constituentid",
            "displayorder",
            "roletype",
            "role",
            "prefix",
            "suffix",
        )
        _relations = _all_relations.join(
            index_source_objects.select("objectid"),
            on="objectid",
            how="semi",
        )
        _all_constituents = _pl.read_csv(
            f"{_base_url}/constituents.csv",
            infer_schema_length=10_000,
        ).select(
            "constituentid",
            "forwarddisplayname",
            "displaydate",
            "visualbrowsernationality",
            "constituenttype",
        )
        _constituents = _all_constituents.join(
            _relations.select("constituentid").unique(),
            on="constituentid",
            how="semi",
        )
        _creators = (
            _relations
            .filter(_pl.col("roletype") == research_config["creator_role_type"])
            .join(_constituents, on="constituentid", how="left")
            .with_columns(
                _pl.col("forwarddisplayname")
                .fill_null("Unidentified constituent")
                .alias("creator_name"),
                _pl.col("displayorder").fill_null(1_000_000),
            )
            .with_columns(
                _pl.concat_str(
                    [
                        _pl.col("prefix").fill_null("").str.strip_chars(),
                        _pl.col("creator_name"),
                        _pl.col("suffix").fill_null("").str.strip_chars(),
                    ],
                    separator=" ",
                )
                .str.replace_all(r"\s+", " ")
                .str.strip_chars()
                .alias("qualified_creator_name")
            )
            .with_columns(
                _pl.concat_str(
                    [
                        _pl.col("qualified_creator_name"),
                        _pl.col("role").fill_null("artist relation"),
                    ],
                    separator=" · ",
                ).alias("creator_relation_label")
            )
            .sort("objectid", "displayorder", "constituentid")
            .group_by("objectid", maintain_order=True)
            .agg(
                _pl.col("creator_name").first().alias("first_artist_name"),
                _pl.col("creator_name")
                .unique(maintain_order=True)
                .alias("creator_names"),
                _pl.col("creator_relation_label")
                .unique(maintain_order=True)
                .alias("creator_relation_labels"),
                _pl.len().alias("creator_relation_count"),
            )
            .with_columns(
                _pl.col("creator_names").list.join("; ").alias("creators"),
                _pl.col("creator_relation_labels")
                .list.join("; ")
                .alias("creator_relations"),
            )
            .drop("creator_names", "creator_relation_labels")
        )
        return _creators, {
            "relations_source": _all_relations.height,
            "relations_working": _relations.height,
            "constituents_source": _all_constituents.height,
            "constituents_working": _constituents.height,
        }

    creators_by_object, creator_source_counts = _load_creator_relations()
    return creators_by_object, creator_source_counts


@app.cell
def _(index_source_objects, research_config):
    import polars as _pl

    def _load_published_images():
        _all_images = _pl.read_csv(
            f"{research_config['dataset_base_url']}/published_images.csv",
            infer_schema_length=10_000,
        ).select(
            _pl.col("depictstmsobjectid").alias("objectid"),
            "uuid",
            "iiifurl",
            "iiifthumburl",
            "viewtype",
            "sequence",
            "width",
            "height",
            "openaccess",
            "assistivetext",
        )
        _images = _all_images.join(
            index_source_objects.select("objectid"),
            on="objectid",
            how="semi",
        )
        _images_by_object = (
            _images
            .with_columns(
                _pl.when(_pl.col("openaccess").fill_null(0) == 1)
                .then(0)
                .otherwise(1)
                .alias("access_rank"),
                _pl.when(_pl.col("viewtype").str.to_lowercase() == "primary")
                .then(0)
                .otherwise(1)
                .alias("view_rank"),
                _pl.col("sequence").fill_null(1_000_000).alias("image_sequence"),
            )
            .sort(
                "objectid",
                "access_rank",
                "view_rank",
                "image_sequence",
                "uuid",
            )
            .group_by("objectid", maintain_order=True)
            .agg(
                _pl.len().alias("published_image_count"),
                (_pl.col("openaccess").fill_null(0) == 1)
                .sum()
                .alias("open_image_count"),
                _pl.col("uuid").first().alias("selected_image_uuid"),
                _pl.col("iiifurl").first().alias("selected_image_url"),
                _pl.col("iiifthumburl").first().alias("selected_thumbnail_url"),
                _pl.col("assistivetext").first().alias("selected_image_alt"),
                _pl.col("width").first().alias("selected_image_width"),
                _pl.col("height").first().alias("selected_image_height"),
                _pl.col("viewtype").first().alias("selected_image_view_type"),
                (_pl.col("openaccess").first().fill_null(0) == 1).alias(
                    "selected_image_open_access"
                ),
            )
        )
        return _images_by_object, {
            "source": _all_images.height,
            "working": _images.height,
        }

    images_by_object, image_source_counts = _load_published_images()
    return image_source_counts, images_by_object


@app.cell
def _(
    attribution_policy,
    creators_by_object,
    images_by_object,
    index_source_objects,
    research_config,
):
    import polars as _pl

    if attribution_policy not in {"source", "first_relation"}:
        raise ValueError("Attribution policy must be 'source' or 'first_relation'")

    index_objects = (
        index_source_objects
        .join(creators_by_object, on="objectid", how="left")
        .join(images_by_object, on="objectid", how="left")
        .with_columns(
            _pl.col("title").fill_null("Untitled"),
            _pl.col("displaydate").fill_null("Date unknown"),
            _pl.col("medium").fill_null("Medium not recorded"),
            _pl.col("attribution").fill_null(research_config["unknown_creator"]),
            _pl.col("creditline").fill_null("Credit line not recorded"),
            _pl.col("classification").fill_null("Unclassified"),
            _pl.col("subclassification").fill_null("Unclassified"),
            _pl.col("visualbrowserclassification").fill_null("Other"),
            _pl.col("first_artist_name").fill_null(
                research_config["unknown_creator"]
            ),
            _pl.col("creators").fill_null(research_config["unknown_creator"]),
            _pl.col("creator_relations").fill_null("Artist relation not recorded"),
            _pl.col("creator_relation_count").fill_null(0),
            _pl.col("published_image_count").fill_null(0),
            _pl.col("open_image_count").fill_null(0),
            _pl.col("selected_image_alt").fill_null(_pl.col("title")),
        )
        .with_columns(
            (
                _pl.col("attribution")
                if attribution_policy == "source"
                else _pl.col("first_artist_name")
            ).alias("display_creator"),
            (_pl.col("published_image_count") > 0).alias("has_published_image"),
            (_pl.col("open_image_count") > 0).alias("has_open_image"),
            _pl.col("beginyear").alias("start_year"),
            (
                _pl.lit("https://www.nga.gov/collection/art-object-page.")
                + _pl.col("objectid").cast(_pl.String)
                + _pl.lit(".html")
            ).alias("object_url"),
        )
        .sort("start_year", "display_creator", "title", nulls_last=True)
    )
    return (index_objects,)


@app.cell(hide_code=True)
def _(collection_objects, index_objects, mo):
    multi_creator_count = index_objects.filter(
        index_objects["creator_relation_count"] > 1
    ).height
    multi_image_count = index_objects.filter(
        index_objects["published_image_count"] > 1
    ).height
    mo.md(f"""
    ### Object-grain models

    `collection_objects` keeps **{collection_objects.height:,} collection
    objects** for historical comparison. `index_objects` enriches the
    **{index_objects.height:,} configured corpus objects** with creator and
    image relationships. The joins preserve **{multi_creator_count:,} objects
    with several creator relations** and **{multi_image_count:,} objects with
    several published images** while retaining one row per object.

    The selected publication image is the first open-access primary view by
    sequence, with another open-access view used when no primary view is
    available. The packet records that image's access status and view type.
    Object rights and reproduction details remain linked to the NGA record.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Historical discovery

    With one row per object, collection-level counts now answer questions about
    works rather than image records. The first view compares the collection's
    visual browser classifications.
    """)
    return


@app.cell
def _(collection_objects):
    import polars as _pl

    collection_classifications = (
        collection_objects.group_by("visualbrowserclassification")
        .agg(_pl.len().alias("object_count"))
        .sort("object_count", descending=True)
    )
    return (collection_classifications,)


@app.cell
def _():
    import observablejs as _obs

    collection_classification_notebook = _obs.Notebook(
        _obs.ojs(
            """
            Plot.plot({
              width,
              height: 420,
              marginLeft: 120,
              x: {grid: true, label: "Collection objects"},
              y: {label: null},
              marks: [
                Plot.barX(collectionClassifications.slice(0, 18), {
                  x: "object_count",
                  y: "visualbrowserclassification",
                  sort: {y: "-x"},
                  fill: "#8b3a2b",
                  tip: {format: {x: ",d"}}
                }),
                Plot.ruleX([0])
              ]
            })
            """,
            key="chart",
        ),
        variables={"collectionClassifications": []},
    )
    collection_classification_chart = collection_classification_notebook.view(
        "chart",
        capture_state=False,
    )
    return collection_classification_chart, collection_classification_notebook


@app.cell
def _(
    collection_classification_chart,
    collection_classification_notebook,
    collection_classifications,
):
    collection_classification_notebook.update_variables(
        {"collectionClassifications": collection_classifications}
    )
    collection_classification_chart
    return


@app.cell
def _(collection_objects):
    import polars as _pl

    dated_collection = collection_objects.filter(
        _pl.col("start_year").is_between(1400, 2020)
    ).select("objectid", "start_year", "visualbrowserclassification")
    return (dated_collection,)


@app.cell
def _():
    import observablejs as _obs

    collection_timeline_notebook = _obs.Notebook(
        _obs.ojs(
            """
            Plot.plot({
              width,
              height: 420,
              marginLeft: 58,
              x: {label: "Object start year"},
              y: {grid: true, label: "Collection objects"},
              color: {legend: true, label: "Classification"},
              marks: [
                Plot.rectY(
                  datedCollection,
                  Plot.binX(
                    {y: "count"},
                    {
                      x: "start_year",
                      fill: "visualbrowserclassification",
                      interval: 5,
                      tip: {format: {x: true, y: ",d", fill: true}}
                    }
                  )
                ),
                Plot.ruleY([0])
              ]
            })
            """,
            key="chart",
        ),
        variables={"datedCollection": []},
    )
    collection_timeline_chart = collection_timeline_notebook.view(
        "chart",
        capture_state=False,
    )
    return collection_timeline_chart, collection_timeline_notebook


@app.cell
def _(collection_timeline_chart, collection_timeline_notebook, dated_collection):
    collection_timeline_notebook.update_variables(
        {"datedCollection": dated_collection}
    )
    collection_timeline_chart
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Follow the drawing peak into the source classification

    The timeline identifies a drawing peak, but the corpus field is a separate
    source column. The next transformation filters drawings dated 1930 through
    1945, then groups them by `classification` to expose the decisive link.
    """)
    return


@app.cell
def _(collection_objects):
    import polars as _pl

    drawing_classification_counts = (
        collection_objects.filter(
            _pl.col("start_year").is_between(1930, 1945),
            _pl.col("visualbrowserclassification") == "drawing",
        )
        .group_by("classification")
        .agg(_pl.len().alias("object_count"))
        .sort("object_count", descending=True)
    )
    return (drawing_classification_counts,)


@app.cell
def _(drawing_classification_counts, mo):
    drawing_classification_table = mo.ui.table(
        drawing_classification_counts.rename(
            {
                "classification": "Source classification",
                "object_count": "Drawing objects, 1930 to 1945",
            }
        ),
        selection=None,
        pagination=False,
        show_column_summaries=False,
        show_data_types=False,
        show_download=False,
        show_search=False,
    )
    drawing_classification_table
    return (drawing_classification_table,)


@app.cell(hide_code=True)
def _(drawing_classification_counts, mo):
    index_drawing_count = drawing_classification_counts.filter(
        drawing_classification_counts["classification"] == "Index of American Design"
    )["object_count"].item()
    drawing_count = drawing_classification_counts["object_count"].sum()
    mo.md(f"""
    **{index_drawing_count:,} of {drawing_count:,} drawings** in this period are
    classified as the **Index of American Design**. The
    [NGA archive finding aid](https://www.nga.gov/research/gallery-archives/finding-aids/index-of-american-design.html)
    traces the collection to the Federal Art Project and its documentation of
    American material culture.

    The corpus rule stays explicit and editable. It is the root of the Index,
    study gallery, and handoff packet.
    """)
    return


@app.cell
def _(index_objects, mo):
    works_with_open_images = index_objects["has_open_image"].sum()
    creators_in_corpus = index_objects["display_creator"].n_unique()
    date_min = index_objects["start_year"].min()
    date_max = index_objects["start_year"].max()
    mo.md(f"""
    ### Index of American Design

    The source revision contains **{index_objects.height:,} Index objects** and
    **{works_with_open_images:,} with an open-access published image**. The
    current attribution rule yields **{creators_in_corpus:,} display attribution
    labels**. Recorded start years span **{date_min} to {date_max}**, with most
    production concentrated from 1935 through 1942.
    """)
    return


@app.cell
def _(index_objects):
    import polars as _pl

    index_by_year = (
        index_objects.filter(_pl.col("start_year").is_not_null())
        .group_by("start_year")
        .agg(
            _pl.len().alias("object_count"),
            _pl.col("display_creator").n_unique().alias("creator_count"),
        )
        .sort("start_year")
    )
    return (index_by_year,)


@app.cell
def _():
    import observablejs as _obs

    index_timeline_notebook = _obs.Notebook(
        _obs.ojs(
            """
            Plot.plot({
              width,
              height: 340,
              marginLeft: 58,
              x: {label: "Recorded start year", tickFormat: "d"},
              y: {grid: true, label: "Index objects"},
              marks: [
                Plot.areaY(indexByYear, {
                  x: "start_year",
                  y: "object_count",
                  curve: "step",
                  fill: "#d7b98e"
                }),
                Plot.lineY(indexByYear, {
                  x: "start_year",
                  y: "object_count",
                  curve: "step",
                  stroke: "#6f2c22",
                  strokeWidth: 2,
                  tip: {format: {x: "d", y: ",d"}}
                }),
                Plot.ruleY([0])
              ]
            })
            """,
            key="chart",
        ),
        variables={"indexByYear": []},
    )
    index_timeline_chart = index_timeline_notebook.view(
        "chart",
        capture_state=False,
    )
    return index_timeline_chart, index_timeline_notebook


@app.cell
def _(index_by_year, index_timeline_chart, index_timeline_notebook):
    index_timeline_notebook.update_variables(
        {"indexByYear": index_by_year}
    )
    index_timeline_chart
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Build the working corpus

    The classification rule above defines the starting corpus. Narrow it by
    recorded date, medium, or creator, then inspect the matching records and
    choose six works for a research packet.
    """)
    return


@app.cell
def _(index_objects, mo):
    _year_values = index_objects["start_year"].drop_nulls()
    _year_start = int(_year_values.min())
    _year_end = int(_year_values.max())

    _year_filter = mo.ui.range_slider(
        start=_year_start,
        stop=_year_end,
        step=1,
        value=[max(_year_start, 1935), min(_year_end, 1942)],
        debounce=True,
        show_value=True,
        label="Recorded start year",
        full_width=True,
    )
    _medium_filter = mo.ui.text(
        placeholder="watercolor, graphite, photograph...",
        debounce=250,
        label="Medium contains",
        full_width=True,
    )
    _creator_filter = mo.ui.text(
        placeholder="creator or attribution",
        debounce=250,
        label="Creator contains",
        full_width=True,
    )

    corpus_filters = mo.ui.dictionary(
        {
            "years": _year_filter,
            "medium": _medium_filter,
            "creator": _creator_filter,
        }
    )
    corpus_filters.hstack(
        widths="equal",
        gap=1.5,
        wrap=True,
    )
    return (corpus_filters,)


@app.cell
def _(corpus_filters, index_objects):
    _filters = corpus_filters.value
    _selected_start, _selected_end = (int(_value) for _value in _filters["years"])
    _medium_query = _filters["medium"].strip().lower()
    _creator_query = _filters["creator"].strip().lower()

    corpus_state = {
        "total_count": index_objects.height,
        "selected_start": _selected_start,
        "selected_end": _selected_end,
        "medium_query": _medium_query,
        "creator_query": _creator_query,
    }
    return (corpus_state,)


@app.cell
def _(corpus_state, index_objects):
    import polars as _pl

    _medium_predicate = (
        _pl.col("medium")
        .str.to_lowercase()
        .str.contains(corpus_state["medium_query"], literal=True)
        if corpus_state["medium_query"]
        else _pl.lit(True)
    )
    _creator_predicate = (
        _pl.concat_str(
            [_pl.col("creators"), _pl.col("attribution")],
            separator=" | ",
        )
        .str.to_lowercase()
        .str.contains(corpus_state["creator_query"], literal=True)
        if corpus_state["creator_query"]
        else _pl.lit(True)
    )

    filtered_object_ids = (
        index_objects.filter(
            _pl.col("start_year").is_between(
                corpus_state["selected_start"],
                corpus_state["selected_end"],
            )
        )
        .filter(_medium_predicate)
        .filter(_creator_predicate)
        .select("objectid")
    )
    return (filtered_object_ids,)


@app.cell
def _(corpus_state, filtered_object_ids, index_objects, research_config):
    import polars as _pl

    _stats = (
        index_objects.join(filtered_object_ids, on="objectid", how="inner")
        .select(
            _pl.len().alias("filtered_count"),
            _pl.col("has_open_image").sum().alias("open_image_count"),
            _pl.col("display_creator").n_unique().alias("creator_count"),
        )
        .row(0, named=True)
    )
    corpus_summary = {
        "name": research_config["corpus_classification"],
        "filtered_count": f"{_stats['filtered_count']:,}",
        "total_count": f"{corpus_state['total_count']:,}",
        "coverage": (
            f"{_stats['filtered_count'] / max(corpus_state['total_count'], 1):.1%}"
        ),
        "date_range": (
            f"{corpus_state['selected_start']} to {corpus_state['selected_end']}"
        ),
        "medium": corpus_state["medium_query"] or "All media",
        "creator": corpus_state["creator_query"] or "All creators",
        "source_revision": research_config["dataset_revision"][:12],
        "open_image_count": f"{_stats['open_image_count']:,}",
        "creator_count": f"{_stats['creator_count']:,}",
    }
    return


@app.cell
def _(filtered_object_ids, index_objects, mo):
    import polars as _pl

    corpus_index_table = mo.ui.table(
        index_objects.join(filtered_object_ids, on="objectid", how="inner")
        .sort("start_year", "display_creator", "title", nulls_last=True)
        .select(
            _pl.col("objectid").alias("Object ID"),
            _pl.col("title").alias("Title"),
            _pl.col("display_creator").alias("Display attribution"),
            _pl.col("displaydate").alias("Date"),
            _pl.col("medium").alias("Medium"),
            _pl.col("accessionnum").alias("Accession"),
            _pl.col("published_image_count").alias("Images"),
            _pl.when(_pl.col("has_open_image"))
            .then(_pl.lit("Yes"))
            .otherwise(_pl.lit("No"))
            .alias("Open image"),
        ),
        selection=None,
        page_size=12,
        show_column_summaries=False,
        show_data_types=False,
        show_download=True,
        show_search=True,
        freeze_columns_left=["Title"],
        wrapped_columns=["Title", "Display attribution", "Medium"],
        column_widths={
            "Title": 260,
            "Display attribution": 220,
            "Date": 100,
            "Medium": 280,
        },
    )
    corpus_index_table
    return (corpus_index_table,)


@app.cell
def _(filtered_object_ids, index_objects):
    import polars as _pl

    filtered_by_year = (
        index_objects.join(filtered_object_ids, on="objectid", how="inner")
        .group_by("start_year")
        .agg(_pl.len().alias("object_count"))
        .sort("start_year")
    )
    return (filtered_by_year,)


@app.cell
def _():
    import observablejs as _obs

    corpus_filter_notebook = _obs.Notebook(
        _obs.ojs(
            """
            Plot.plot({
              width,
              height: 230,
              marginLeft: 52,
              x: {label: "Recorded start year", tickFormat: "d"},
              y: {grid: true, label: "Works"},
              marks: [
                Plot.barY(filteredByYear, {
                  x: "start_year",
                  y: "object_count",
                  fill: "#8b3a2b",
                  tip: {format: {x: "d", y: ",d"}}
                }),
                Plot.ruleY([0])
              ]
            })
            """,
            key="chart",
        ),
        variables={"filteredByYear": []},
    )
    corpus_filter_chart = corpus_filter_notebook.view(
        "chart",
        capture_state=False,
    )
    return corpus_filter_chart, corpus_filter_notebook


@app.cell
def _(corpus_filter_chart, corpus_filter_notebook, filtered_by_year):
    corpus_filter_notebook.update_variables(
        {"filteredByYear": filtered_by_year}
    )
    corpus_filter_chart
    return


@app.cell
def _(filtered_object_ids, index_objects):
    import polars as _pl

    gallery_objects = (
        index_objects.join(filtered_object_ids, on="objectid", how="inner")
        .filter(
            _pl.col("selected_image_open_access")
            & _pl.col("selected_thumbnail_url").is_not_null()
        )
        .select(
            "objectid",
            "title",
            "display_creator",
            "displaydate",
            "accessionnum",
            "selected_thumbnail_url",
            "selected_image_alt",
            "start_year",
        )
    )
    return (gallery_objects,)


@app.cell
def _(corpus_state, filtered_object_ids, gallery_objects, research_config):
    _page_size = research_config["gallery_page_size"]
    gallery_context = {
        "candidate_count": gallery_objects.height,
        "page_count": max(
            (gallery_objects.height + _page_size - 1) // _page_size,
            1,
        ),
        "page_size": _page_size,
        "selection_limit": research_config["packet_limit"],
        "corpus": {
            "name": research_config["corpus_classification"],
            "matching_count": filtered_object_ids.height,
            "selected_start": corpus_state["selected_start"],
            "selected_end": corpus_state["selected_end"],
            "medium_query": corpus_state["medium_query"],
            "creator_query": corpus_state["creator_query"],
            "date_range": (
                f"{corpus_state['selected_start']} to {corpus_state['selected_end']}"
            ),
            "medium": corpus_state["medium_query"] or "All media",
            "creator": corpus_state["creator_query"] or "All creators",
        },
    }
    return (gallery_context,)


@app.cell
def _(gallery_context, mo):
    _page = mo.ui.dropdown(
        options={
            f"Page {_page_number}": _page_number
            for _page_number in range(1, gallery_context["page_count"] + 1)
        },
        value="Page 1",
        label="Tray page",
        full_width=True,
    )
    _sort = mo.ui.dropdown(
        options={
            "Date, then creator": "chronological",
            "Creator, then title": "creator",
            "Title": "title",
        },
        value="Date, then creator",
        label="Order works by",
        full_width=True,
    )
    study_control_values = mo.ui.dictionary({"sort": _sort, "page": _page})
    study_control_values.hstack(
        widths="equal",
        gap=1.5,
        wrap=True,
    )
    return (study_control_values,)


@app.cell
def _():
    gallery_styles_source = """
            <style>
              :scope {
                color: #f4efe7;
                font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont,
                  "Segoe UI", sans-serif;
              }

              .study-gallery {
                display: grid;
                gap: 1rem;
              }

              .study-gallery__bar {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                padding-bottom: 0.8rem;
                border-bottom: 1px solid rgb(244 239 231 / 20%);
              }

              .study-gallery__status {
                margin: 0;
                color: #d6cabd;
                font-size: 0.82rem;
                letter-spacing: 0.04em;
              }

              .study-gallery__clear {
                border: 1px solid rgb(244 239 231 / 34%);
                border-radius: 0.2rem;
                padding: 0.45rem 0.7rem;
                color: #f4efe7;
                background: transparent;
                font: inherit;
                font-size: 0.78rem;
                cursor: pointer;
              }

              .study-gallery__grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(155px, 1fr));
                gap: 0.85rem;
              }

              .study-card {
                position: relative;
                display: grid;
                grid-template-rows: 180px auto;
                min-width: 0;
                overflow: hidden;
                border: 1px solid rgb(244 239 231 / 15%);
                border-radius: 0.25rem;
                padding: 0;
                color: inherit;
                background: #242625;
                text-align: left;
                cursor: pointer;
              }

              .study-card:hover,
              .study-card:focus-visible {
                border-color: #d2a45f;
              }

              .study-card[aria-pressed="true"] {
                border-color: #d2a45f;
                box-shadow: inset 0 0 0 2px #d2a45f;
              }

              .study-card__image {
                width: 100%;
                height: 100%;
                object-fit: contain;
                background: #171918;
              }

              .study-card__copy {
                display: grid;
                gap: 0.35rem;
                padding: 0.75rem;
              }

              .study-card__title {
                display: -webkit-box;
                overflow: hidden;
                font-family: ui-serif, Georgia, Cambria, serif;
                font-size: 0.92rem;
                line-height: 1.25;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 2;
              }

              .study-card__meta {
                overflow: hidden;
                color: #bdb4aa;
                font-size: 0.72rem;
                line-height: 1.35;
                text-overflow: ellipsis;
                white-space: nowrap;
              }

              .study-card__order {
                position: absolute;
                top: 0.55rem;
                right: 0.55rem;
                display: grid;
                place-items: center;
                width: 1.8rem;
                height: 1.8rem;
                border-radius: 50%;
                color: #201d18;
                background: #d2a45f;
                font-size: 0.76rem;
                font-weight: 750;
              }

              .study-gallery__empty {
                margin: 0;
                padding: 3rem 1rem;
                border: 1px solid rgb(244 239 231 / 16%);
                color: #d6cabd;
                text-align: center;
              }

              @media (max-width: 600px) {
                .study-gallery__grid {
                  grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                .study-card {
                  grid-template-rows: 150px auto;
                }
              }
            </style>
            """
    return (gallery_styles_source,)


@app.cell
def _():
    gallery_controller_source = """
            galleryController = {
              const root = document.createElement("section");
              root.className = "study-gallery";
              root.setAttribute("aria-label", "Selectable works");

              let objects = [];
              let limit = 6;
              let fingerprint = null;
              let selected = [];
              let notice = "";
              let action = "hydrate";

              function publish() {
                root.dispatchEvent(new Event("input", {bubbles: true}));
              }

              function toggle(objectId) {
                if (selected.includes(objectId)) {
                  selected = selected.filter((id) => id !== objectId);
                  notice = "Work removed from packet";
                  action = "changed";
                  render();
                  publish();
                  return;
                }

                if (selected.length >= limit) {
                  notice = `The packet holds ${limit} works`;
                  render();
                  return;
                }

                selected = [...selected, objectId];
                notice = "Work added to packet";
                action = "changed";
                render();
                publish();
              }

              function render() {
                const bar = document.createElement("div");
                bar.className = "study-gallery__bar";

                const status = document.createElement("p");
                status.className = "study-gallery__status";
                status.setAttribute("aria-live", "polite");
                status.textContent = notice ||
                  `${selected.length} of ${limit} works selected`;

                const clear = document.createElement("button");
                clear.type = "button";
                clear.className = "study-gallery__clear";
                clear.textContent = "Clear selection";
                clear.disabled = selected.length === 0;
                clear.addEventListener("click", () => {
                  selected = [];
                  notice = "Selection cleared";
                  action = "cleared";
                  render();
                  publish();
                });

                bar.append(status, clear);

                if (objects.length === 0) {
                  const empty = document.createElement("p");
                  empty.className = "study-gallery__empty";
                  empty.textContent = "No works match the current corpus filters.";
                  root.replaceChildren(bar, empty);
                  return;
                }

                const grid = document.createElement("div");
                grid.className = "study-gallery__grid";

                for (const work of objects) {
                  const card = document.createElement("button");
                  const isSelected = selected.includes(work.objectid);
                  card.type = "button";
                  card.className = "study-card";
                  card.setAttribute("aria-pressed", String(isSelected));
                  card.setAttribute(
                    "aria-label",
                    `${isSelected ? "Remove" : "Add"} ${work.title} ${isSelected ? "from" : "to"} packet`
                  );
                  card.addEventListener("click", () => toggle(work.objectid));

                  const image = document.createElement("img");
                  image.className = "study-card__image";
                  image.src = work.selected_thumbnail_url;
                  image.alt = work.selected_image_alt || work.title;
                  image.loading = "lazy";
                  image.decoding = "async";

                  const copy = document.createElement("span");
                  copy.className = "study-card__copy";

                  const title = document.createElement("strong");
                  title.className = "study-card__title";
                  title.textContent = work.title;

                  const creator = document.createElement("span");
                  creator.className = "study-card__meta";
                  creator.textContent = work.display_creator;

                  const details = document.createElement("span");
                  details.className = "study-card__meta";
                  details.textContent = `${work.displaydate} · ${work.accessionnum}`;

                  copy.append(title, creator, details);
                  card.append(image, copy);

                  if (isSelected) {
                    const order = document.createElement("span");
                    order.className = "study-card__order";
                    order.textContent = String(selected.indexOf(work.objectid) + 1);
                    order.setAttribute("aria-hidden", "true");
                    card.append(order);
                  }

                  grid.append(card);
                }

                root.replaceChildren(bar, grid);
              }

              Object.defineProperty(root, "value", {
                get() {
                  return {objectIds: [...selected], action};
                },
                set(next) {
                  selected = Array.isArray(next?.objectIds)
                    ? [...new Set(next.objectIds)].slice(0, limit)
                    : [];
                  action = next?.action || "hydrate";
                  notice = "";
                  render();
                }
              });

              render();
              return {
                root,
                update(nextObjects, nextLimit, nextFingerprint, nextSelection) {
                  const corpusChanged = fingerprint !== null &&
                    fingerprint !== nextFingerprint;
                  objects = Array.isArray(nextObjects) ? nextObjects : [];
                  limit = nextLimit;
                  fingerprint = nextFingerprint;
                  if (corpusChanged) {
                    selected = [];
                    notice = "Selection cleared after corpus filters changed";
                    action = "corpus";
                  } else {
                    selected = Array.isArray(nextSelection)
                      ? [...new Set(nextSelection)].slice(0, limit)
                      : selected.slice(0, limit);
                    notice = "";
                    action = "hydrate";
                  }
                  render();
                  if (corpusChanged) setTimeout(publish, 0);
                  return root;
                }
              };
            }
            """
    return (gallery_controller_source,)


@app.cell
def _(gallery_controller_source, gallery_styles_source):
    import observablejs as _obs

    _notebook = _obs.Notebook(
        _obs.html(gallery_styles_source, key="gallery_styles"),
        _obs.ojs(
            gallery_controller_source,
            key="gallery_controller",
            display=False,
        ),
        _obs.ojs(
            """
            viewof selectionState = galleryController.update(
              galleryObjects,
              selectionLimit,
              corpusFingerprint,
              packetSelection
            )
            """,
            key="selection_gallery",
        ),
        variables={
            "corpusFingerprint": "",
            "galleryObjects": [],
            "packetSelection": [],
            "selectionLimit": 6,
        },
        theme="near-midnight",
    )
    gallery_notebook = _notebook
    gallery_view = _notebook.view("gallery_styles", "selection_gallery")
    return gallery_notebook, gallery_view


@app.cell
def _(study_control_values):
    _controls = study_control_values.value
    _order = _controls["sort"]
    _order_columns = {
        "chronological": ["start_year", "display_creator", "title", "objectid"],
        "creator": ["display_creator", "title", "start_year", "objectid"],
        "title": ["title", "display_creator", "start_year", "objectid"],
    }
    _order_labels = {
        "chronological": "Date, then creator",
        "creator": "Creator, then title",
        "title": "Title",
    }
    _page_number = int(_controls["page"])
    study_order = {
        "order": _order,
        "order_columns": _order_columns[_order],
        "order_label": _order_labels[_order],
        "page_number": _page_number,
    }
    return (study_order,)


@app.cell
def _(gallery_context, gallery_objects, study_order):
    import json as _json

    _page_number = study_order["page_number"]
    _offset = (_page_number - 1) * gallery_context["page_size"]
    _records = (
        gallery_objects.sort(
            study_order["order_columns"],
            nulls_last=True,
        )
        .slice(_offset, gallery_context["page_size"])
        .select(
            "objectid",
            "title",
            "display_creator",
            "displaydate",
            "accessionnum",
            "selected_thumbnail_url",
            "selected_image_alt",
        )
        .to_dicts()
    )
    _fingerprint = _json.dumps(
        gallery_context["corpus"],
        sort_keys=True,
    )
    gallery_state = {
        **gallery_context,
        "records": _records,
        "order": study_order["order"],
        "order_label": study_order["order_label"],
        "page_number": _page_number,
        "page_window": (
            f"{_offset + 1:,} to {_offset + len(_records):,}"
            if _records
            else "No works"
        ),
        "fingerprint": _fingerprint,
    }
    return (gallery_state,)


@app.cell
def _(
    gallery_notebook,
    gallery_state,
    gallery_view,
    get_selected_object_ids,
):
    gallery_notebook.update_variables(
        {
            "corpusFingerprint": gallery_state["fingerprint"],
            "galleryObjects": gallery_state["records"],
            "packetSelection": get_selected_object_ids(),
            "selectionLimit": gallery_state["selection_limit"],
        }
    )
    gallery_view
    return


@app.cell
def _(mo):
    get_selected_object_ids, set_selected_object_ids = mo.state([])
    return get_selected_object_ids, set_selected_object_ids


@app.cell
def _(gallery_view, get_selected_object_ids, set_selected_object_ids):
    _ = gallery_view.value
    _view_state = gallery_view.state
    selected_object_ids = get_selected_object_ids()
    if (
        not _view_state.pending
        and _view_state.input_revision is not None
        and _view_state.settled_revision == _view_state.input_revision
    ):
        _result = _view_state.result("selection_gallery")
        if _result.status == "success":
            _selection = _result.values.get("selectionState", {})
            _next_ids = [
                int(_object_id)
                for _object_id in _selection.get("objectIds", [])
            ]
            if (
                _selection.get("action") in {"changed", "cleared", "corpus"}
                and _next_ids != selected_object_ids
            ):
                selected_object_ids = _next_ids
                set_selected_object_ids(_next_ids)
    return (selected_object_ids,)


@app.cell
def _(index_objects, selected_object_ids):
    import polars as _pl

    if selected_object_ids:
        _selection_order = _pl.DataFrame(
            {
                "objectid": selected_object_ids,
                "packet_order": range(1, len(selected_object_ids) + 1),
            }
        )
        packet_objects = _selection_order.join(
            index_objects, on="objectid", how="left"
        ).sort("packet_order")
    else:
        packet_objects = index_objects.head(0).with_columns(
            _pl.lit(None, dtype=_pl.Int64).alias("packet_order")
        )
    return (packet_objects,)


@app.cell
def _(gallery_state, packet_objects):
    _selected_count = packet_objects.height
    _selection_limit = gallery_state["selection_limit"]
    _remaining_count = max(_selection_limit - _selected_count, 0)
    study_summary = {
        "matching_count": f"{gallery_state['corpus']['matching_count']:,}",
        "shown_count": f"{len(gallery_state['records']):,}",
        "candidate_count": f"{gallery_state['candidate_count']:,}",
        "page_number": str(gallery_state["page_number"]),
        "page_count": str(gallery_state["page_count"]),
        "page_size": str(gallery_state["page_size"]),
        "page_window": gallery_state["page_window"],
        "order": gallery_state["order"],
        "order_label": gallery_state["order_label"],
        "selected_count": str(_selected_count),
        "selection_limit": str(_selection_limit),
        "selection_progress": f"{_selected_count} of {_selection_limit}",
        "selection_status": (
            "Packet ready"
            if _selected_count == _selection_limit
            else f"Choose {_remaining_count} more"
        ),
        "date_range": gallery_state["corpus"]["date_range"],
        "medium": gallery_state["corpus"]["medium"],
        "creator": gallery_state["corpus"]["creator"],
    }
    return (study_summary,)


@app.cell
def _(mo, study_summary):
    mo.md(f"""
    **{study_summary["selection_progress"]} works selected.**
    {study_summary["selection_status"]} for the research packet.
    """)
    return


@app.cell
def _(gallery_objects, packet_objects, study_order):
    _objects = (
        gallery_objects.sort(
            study_order["order_columns"],
            nulls_last=True,
        )
        .select("objectid")
        .with_row_index("study_position", offset=1)
        .join(packet_objects, on="objectid", how="inner")
        .sort("packet_order")
    )
    packet_records = _objects.select(
        "packet_order",
        "objectid",
        "study_position",
        "title",
        "display_creator",
        "attribution",
        "creators",
        "creator_relations",
        "displaydate",
        "beginyear",
        "endyear",
        "medium",
        "creditline",
        "accessionnum",
        "object_url",
        "selected_image_url",
        "selected_thumbnail_url",
        "selected_image_uuid",
        "selected_image_view_type",
        "selected_image_open_access",
    ).to_dicts()
    return (packet_records,)


@app.cell
def _(attribution_policy, research_config):
    packet_policy = {
        "corpus": research_config["corpus_classification"],
        "creator_role_type": research_config["creator_role_type"],
        "display_attribution_policy": attribution_policy,
        "dataset_revision": research_config["dataset_revision"],
        "selection_limit": research_config["packet_limit"],
    }
    return (packet_policy,)


@app.cell
def _(gallery_state, packet_policy):
    packet_context = {
        **packet_policy,
        "corpus_filters": gallery_state["corpus"],
        "study": {
            "order": gallery_state["order"],
            "order_label": gallery_state["order_label"],
            "page": gallery_state["page_number"],
            "page_count": gallery_state["page_count"],
            "page_size": gallery_state["page_size"],
            "page_window": gallery_state["page_window"],
            "candidate_count": gallery_state["candidate_count"],
        },
    }
    return (packet_context,)


@app.cell
def _(packet_records):
    import csv as _csv
    import io as _io

    _buffer = _io.StringIO()
    if packet_records:
        _writer = _csv.DictWriter(_buffer, fieldnames=packet_records[0].keys())
        _writer.writeheader()
        _writer.writerows(packet_records)
    packet_csv = _buffer.getvalue()
    return (packet_csv,)


@app.cell
def _(packet_context, packet_records):
    _filters = packet_context["corpus_filters"]
    _study = packet_context["study"]
    _lines = [
        "# Index of American Design research packet",
        "",
        f"Corpus: {packet_context['corpus']}",
        f"Creator role type: {packet_context['creator_role_type']}",
        (f"Display attribution policy: {packet_context['display_attribution_policy']}"),
        f"NGA data revision: {packet_context['dataset_revision']}",
        f"Recorded start year filter: {_filters['date_range']}",
        f"Medium contains: {_filters['medium']}",
        f"Creator contains: {_filters['creator']}",
        f"Study order: {_study['order_label']}",
        (
            f"Study page: {_study['page']} of {_study['page_count']} "
            f"({_study['page_window']})"
        ),
        "",
        (
            "Source data is CC0. Selected records link to NGA open-access "
            "published images and object records."
        ),
        "",
    ]
    for _record in packet_records:
        _lines.extend(
            [
                f"## {_record['packet_order']}. {_record['title']}",
                "",
                f"- Display attribution: {_record['display_creator']}",
                f"- Source attribution: {_record['attribution']}",
                f"- Artist relations: {_record['creator_relations']}",
                f"- Date: {_record['displaydate']}",
                f"- Medium: {_record['medium']}",
                f"- Credit line: {_record['creditline']}",
                f"- Accession: {_record['accessionnum']}",
                f"- NGA record: {_record['object_url']}",
                f"- IIIF image: {_record['selected_image_url']}",
                f"- Image view type: {_record['selected_image_view_type']}",
                f"- Image open access: {_record['selected_image_open_access']}",
                "",
            ]
        )
    packet_markdown = "\n".join(_lines)
    return (packet_markdown,)


@app.cell
def _(packet_context, packet_records):
    import html as _html

    _cards = []
    for _record in packet_records:
        _title = _html.escape(str(_record["title"]))
        _creator = _html.escape(str(_record["display_creator"]))
        _source_attribution = _html.escape(str(_record["attribution"]))
        _creator_relations = _html.escape(str(_record["creator_relations"]))
        _date = _html.escape(str(_record["displaydate"]))
        _medium = _html.escape(str(_record["medium"]))
        _creditline = _html.escape(str(_record["creditline"]))
        _accession = _html.escape(str(_record["accessionnum"]))
        _object_url = _html.escape(str(_record["object_url"]), quote=True)
        _thumbnail_url = _html.escape(
            str(_record["selected_thumbnail_url"] or ""), quote=True
        )
        _cards.append(
            f"""
            <article class="work">
              <p class="number">{_record["packet_order"]:02d}</p>
              <img src="{_thumbnail_url}" alt="{_title}" />
              <div>
                <h2>{_title}</h2>
                <p>{_creator} · {_date}</p>
                <p>Source attribution: {_source_attribution}</p>
                <p>Artist relations: {_creator_relations}</p>
                <p>{_medium}</p>
                <p>{_creditline}</p>
                <p>Accession {_accession} · <a href="{_object_url}">NGA object record</a></p>
              </div>
            </article>
            """
        )

    _filters = packet_context["corpus_filters"]
    packet_html = f"""<!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Index of American Design research packet</title>
        <style>
          body {{ max-width: 72rem; margin: 3rem auto; padding: 0 2rem;
            color: #26231e; font: 16px/1.5 system-ui, sans-serif; }}
          header {{ padding-bottom: 2rem; border-bottom: 2px solid #26231e; }}
          h1, h2 {{ font-family: Georgia, serif; font-weight: 500; }}
          h1 {{ font-size: 3rem; line-height: 1; }}
          .provenance {{ color: #6d665c; }}
          .work {{ display: grid; grid-template-columns: 2rem 12rem 1fr; gap: 1.5rem;
            padding: 2rem 0; border-bottom: 1px solid #c9c2b6; break-inside: avoid; }}
          .work img {{ width: 100%; height: 11rem; object-fit: contain; background: #eee9df; }}
          .work h2, .work p {{ margin: 0 0 0.5rem; }}
          .number {{ color: #823629; font-family: Georgia, serif; font-size: 1.25rem; }}
          a {{ color: #823629; }}
          @media (max-width: 700px) {{ .work {{ grid-template-columns: 2rem 1fr; }}
            .work img {{ grid-column: 2; }} }}
          @media print {{ body {{ margin: 0; }} }}
        </style>
      </head>
      <body>
        <header>
          <p>Research handoff · {len(packet_records)} of {packet_context["selection_limit"]} works</p>
          <h1>Index of American Design</h1>
          <p class="provenance">NGA data revision {packet_context["dataset_revision"]}.
            Filters: years {_html.escape(_filters["date_range"])};
            medium {_html.escape(_filters["medium"])};
            creator {_html.escape(_filters["creator"])}.</p>
        </header>
        <main>{"".join(_cards)}</main>
        <footer>
          <p>Source data is CC0. Follow each NGA object record for image and credit details.</p>
        </footer>
      </body>
    </html>
    """
    return (packet_html,)


@app.cell
def _(packet_context, packet_records):
    import json as _json

    _filters = packet_context["corpus_filters"]
    _study = packet_context["study"]
    packet_manifest = _json.dumps(
        {
            "source": {
                "dataset": "National Gallery of Art Open Data",
                "revision": packet_context["dataset_revision"],
                "license": "CC0",
                "program_url": (
                    "https://www.nga.gov/open-access-images/open-data.html"
                ),
            },
            "corpus": {
                "classification": packet_context["corpus"],
                "creator_role_type": packet_context["creator_role_type"],
                "display_attribution_policy": packet_context[
                    "display_attribution_policy"
                ],
                "filters": {
                    "recorded_start_year": [
                        _filters["selected_start"],
                        _filters["selected_end"],
                    ],
                    "medium_contains": _filters["medium_query"] or None,
                    "creator_contains": _filters["creator_query"] or None,
                },
                "matching_record_count": _filters["matching_count"],
            },
            "study": {
                "order": _study["order"],
                "page": _study["page"],
                "page_count": _study["page_count"],
                "page_size": _study["page_size"],
                "page_window": _study["page_window"],
                "open_image_candidate_count": _study["candidate_count"],
                "image_selection_policy": (
                    "Open-access images first, then primary view, source sequence, "
                    "and UUID"
                ),
            },
            "selection": {
                "limit": packet_context["selection_limit"],
                "items": [
                    {
                        "object_id": _record["objectid"],
                        "study_position": _record["study_position"],
                    }
                    for _record in packet_records
                ],
                "record_count": len(packet_records),
            },
        },
        indent=2,
    )
    return (packet_manifest,)


@app.cell
def _(packet_csv, packet_manifest):
    packet_data_files = {
        "index-research-packet.csv": packet_csv,
        "manifest.json": packet_manifest,
    }
    return (packet_data_files,)


@app.cell
def _(packet_html, packet_markdown):
    packet_reading_files = {
        "index-research-packet.html": packet_html,
        "index-research-packet.md": packet_markdown,
    }
    return (packet_reading_files,)


@app.cell
def _(packet_data_files, packet_reading_files):
    packet_documents = packet_data_files | packet_reading_files
    return (packet_documents,)


@app.cell
def _(packet_context, packet_records):
    _selected_count = len(packet_records)
    _selection_limit = packet_context["selection_limit"]
    packet_summary = {
        "title": "Index of American Design research packet",
        "corpus": packet_context["corpus"],
        "selected_count": str(_selected_count),
        "selection_limit": str(_selection_limit),
        "source_revision": packet_context["dataset_revision"][:12],
        "status": (
            "Ready for handoff"
            if _selected_count == _selection_limit
            else "Selection in progress"
        ),
    }
    return (packet_summary,)


@app.cell
def _(mo, packet_records):
    import html as _html

    if packet_records:
        _packet_style = """
        <style>
          .packet-works {
            display: grid;
            gap: 0;
          }

          .packet-work {
            display: grid;
            grid-template-columns: 2.5rem 12rem minmax(0, 1fr);
            gap: 1.5rem;
            padding: 1.5rem 0;
            border-bottom: 1px solid #c9c2b6;
          }

          .packet-work__number {
            color: #823629;
            font-family: ui-serif, Georgia, Cambria, serif;
            font-size: 1.25rem;
          }

          .packet-work__image {
            display: grid;
            place-items: center;
            min-height: 9rem;
            background: #eee9df;
          }

          .packet-work__image img {
            width: 100%;
            height: 10rem;
            object-fit: contain;
          }

          .packet-work__image-missing {
            color: #6d665c;
            font-size: 0.72rem;
          }

          .packet-work__copy {
            min-width: 0;
          }

          .packet-work__kicker {
            margin: 0 0 0.35rem;
            color: #823629;
            font-size: 0.65rem;
            font-weight: 750;
            letter-spacing: 0.09em;
            text-transform: uppercase;
          }

          .packet-work h3 {
            margin: 0;
            font-family: ui-serif, Georgia, Cambria, serif;
            font-size: 1.45rem;
            font-weight: 500;
            letter-spacing: -0.025em;
            line-height: 1.05;
          }

          .packet-work__creator {
            margin: 0.45rem 0 1rem;
            color: #6d665c;
            font-family: ui-serif, Georgia, Cambria, serif;
            font-size: 0.95rem;
          }

          .packet-work dl {
            display: grid;
            gap: 0.4rem;
            margin: 0 0 1rem;
          }

          .packet-work dl div {
            display: grid;
            grid-template-columns: 4rem minmax(0, 1fr);
            gap: 0.75rem;
          }

          .packet-work dt {
            color: #6d665c;
            font-size: 0.65rem;
            font-weight: 750;
            letter-spacing: 0.07em;
            text-transform: uppercase;
          }

          .packet-work dd {
            margin: 0;
            font-size: 0.8rem;
            line-height: 1.4;
          }

          .packet-work a {
            border-bottom: 1px solid currentColor;
            color: #823629;
            font-size: 0.7rem;
            font-weight: 750;
            letter-spacing: 0.06em;
            text-decoration: none;
            text-transform: uppercase;
          }

          @media (max-width: 640px) {
            .packet-work {
              grid-template-columns: 2rem minmax(0, 1fr);
            }

            .packet-work__image {
              grid-column: 2;
            }

            .packet-work__copy {
              grid-column: 2;
            }
          }
        </style>
        """
        _packet_items = []
        for _record in packet_records:
            _image = (
                f'<img src="{_html.escape(_record["selected_thumbnail_url"] or "")}" '
                f'alt="{_html.escape(_record["title"])}" loading="lazy">'
                if _record["selected_thumbnail_url"]
                else '<span class="packet-work__image-missing">Image unavailable</span>'
            )
            _packet_items.append(
                f"""
                <article class="packet-work">
                  <div class="packet-work__number">{_record["packet_order"]:02d}</div>
                  <div class="packet-work__image">{_image}</div>
                  <div class="packet-work__copy">
                    <p class="packet-work__kicker">{_html.escape(_record["accessionnum"] or "")}</p>
                    <h3>{_html.escape(_record["title"])}</h3>
                    <p class="packet-work__creator">{_html.escape(_record["display_creator"])}</p>
                    <dl>
                      <div><dt>Source</dt><dd>{_html.escape(_record["attribution"])}</dd></div>
                      <div><dt>Relations</dt><dd>{_html.escape(_record["creator_relations"])}</dd></div>
                      <div><dt>Date</dt><dd>{_html.escape(_record["displaydate"])}</dd></div>
                      <div><dt>Medium</dt><dd>{_html.escape(_record["medium"])}</dd></div>
                      <div><dt>Credit</dt><dd>{_html.escape(_record["creditline"])}</dd></div>
                    </dl>
                    <a href="{_html.escape(_record["object_url"])}" target="_blank" rel="noreferrer">Open NGA record</a>
                  </div>
                </article>
                """
            )
        _packet_html = (
            _packet_style
            + '<section class="packet-works">'
            + "".join(_packet_items)
            + "</section>"
        )
        _preview = mo.Html(_packet_html)
    else:
        _preview = mo.md("Select works in the **Study** view to assemble the packet.")
    _preview
    return


@app.cell
def _(mo, packet_objects):
    import polars as _pl

    _table_data = packet_objects.select(
        _pl.col("packet_order").alias("No."),
        _pl.col("title").alias("Title"),
        _pl.col("display_creator").alias("Display attribution"),
        _pl.col("displaydate").alias("Date"),
        _pl.col("medium").alias("Medium"),
        _pl.col("accessionnum").alias("Accession"),
    )
    packet_object_table = mo.ui.table(
        _table_data,
        selection=None,
        pagination=False,
        show_column_summaries=False,
        show_data_types=False,
        show_download=False,
        show_search=False,
        wrapped_columns=["Title", "Display attribution", "Medium"],
        column_widths={"Title": 260, "Display attribution": 220, "Medium": 260},
    )
    packet_object_table
    return (packet_object_table,)


@app.cell
def _(packet_documents, packet_summary):
    import io as _io
    import zipfile as _zipfile

    _buffer = _io.BytesIO()
    with _zipfile.ZipFile(
        _buffer,
        mode="w",
        compression=_zipfile.ZIP_DEFLATED,
    ) as _packet_zip:
        for _filename, _contents in packet_documents.items():
            _packet_zip.writestr(_filename, _contents)

    packet_archive = {
        "data": _buffer.getvalue(),
        "ready": packet_summary["status"] == "Ready for handoff",
    }
    return (packet_archive,)


@app.cell
def _(mo, packet_archive):
    packet_download_widget = mo.download(
        data=packet_archive["data"],
        filename="nga-index-research-packet.zip",
        mimetype="application/zip",
        disabled=not packet_archive["ready"],
        label="Download handoff bundle",
    )
    packet_download_widget
    return (packet_download_widget,)


if __name__ == "__main__":
    app.run()
