# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo-studio[deno]"]
#
# [tool.marimo-studio]
# default = "gallery"
# preserve_session = false
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def imports():
    import marimo as mo

    return (mo,)


@app.cell
def studio_view_data():
    thumbnail = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
    studio_artworks = [
        {
            "objectid": index + 1,
            "title": f"Acceptance artwork {index + 1}",
            "year": 1935 + index,
            "name": f"Artist {index % 4 + 1}",
            "type": "Drawing" if index % 2 == 0 else "Print",
            "thumburl": thumbnail,
            "public": index % 3 != 0,
        }
        for index in range(12)
    ]
    studio_index_artworks = studio_artworks
    studio_summary = {
        "artworks": len(studio_artworks),
        "artists": 4,
        "public_domain": 8,
        "index_drawings": 12,
        "index_artists": 4,
    }
    return studio_artworks, studio_index_artworks, studio_summary


@app.cell
def classification_bar_chart(mo):
    mo.md("### Producer: classification_bar_chart")
    return


@app.cell
def classification_waffle_chart(mo):
    mo.md("### Producer: classification_waffle_chart")
    return


@app.cell
def artist_totals_chart(mo):
    mo.md("### Producer: artist_totals_chart")
    return


@app.cell
def artwork_totals(mo):
    artwork_totals_df = mo.ui.table(
        [
            {
                "name": f"Artist {index}",
                "public": index % 2 == 0,
                "name_count": 6 - index,
            }
            for index in range(1, 5)
        ]
    )
    return (artwork_totals_df,)


@app.cell
def collection_timeline_chart(mo):
    mo.md("### Producer: collection_timeline_chart")
    return


@app.cell
def notable_period_chart(mo):
    mo.md("### Producer: notable_period_chart")
    return


@app.cell
def index_drawing_count(mo):
    mo.md("### Producer: index_drawing_count")
    return


@app.cell
def index_gallery(mo):
    mo.md("### Producer: index_gallery")
    return


@app.cell
def index_finding(mo):
    mo.md("### Producer: index_finding")
    return


if __name__ == "__main__":
    app.run()
