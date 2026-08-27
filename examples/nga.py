# /// script
# dependencies = []
# requires-python = ">=3.11"
#
# [tool.marimo-studio]
# default = "overview"
# preserve_session = false
# runtime = "server"
# runtimes = ["server"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
#
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def introduction(mo):
    mo.md(r"""
    # Exploring Art with Python, marimo, Polars, and Observable Plot

    _A Python and marimo adaptation of Trevor Manz's
    [Deno notebook post](https://deno.com/blog/exploring-art-with-typescript-and-jupyter)._

    ## Introduction

    Computational notebooks combine code, prose, and visualizations in a single
    document. This marimo notebook is backed by a plain Python file.

    Marimo provides reactive execution and notebook metadata. Polars
    handles the relational transformations. `pyobservablejs` renders Observable
    Plot and custom web outputs alongside Python.

    We will analyze the National Gallery of Art's Open Access data to see which
    artworks have public-domain images, who created them, when they were made,
    and which patterns emerge. The investigation ends with a closer look at a
    large cluster of public-domain drawings from the 1930s and 1940s.
    """)
    return


@app.cell(hide_code=True)
def dataset_overview(mo):
    mo.md(r"""
    ## The Dataset

    The **National Gallery of Art (NGA)
    [Open Data Program](https://www.nga.gov/open-access-images/open-data.html)**
    provides metadata for more than **130,000 artworks** and their creators. The
    data is published
    [on GitHub](https://github.com/NationalGalleryOfArt/opendata/tree/main/data)
    under a
    [Creative Commons 0 (CC0)](https://creativecommons.org/public-domain/cc0/)
    license.

    The collection spans paintings, sculptures, drawings, photographs, prints,
    and other forms. Its records include work by Mary Cassatt, M. C. Escher,
    Vincent van Gogh, Pablo Picasso, Georgia O'Keeffe, and many other artists.

    The analysis uses four related CSV tables:

    - **`objects.csv`** contains titles, dates, materials, and classifications.
    - **`constituents.csv`** describes artists and other people or organizations.
    - **`published_images.csv`** links artworks to images and their open-access
      status.
    - **`objects_constituents.csv`** connects artworks with their constituents.

    We will clean and join these tables into one dataframe, then use it to
    identify public-domain images, explore subsets, and view the artworks.
    """)
    return


@app.cell(hide_code=True)
def artwork_records_context(mo):
    mo.md(r"""
    ## Loading and cleaning the data

    ### Artwork records

    We start with `objects.csv` and keep the object identifier, title, year,
    medium, and artwork classification.
    """)
    return


@app.cell
def artwork_records(pl, read_dataset):
    objects_df = read_dataset("objects.csv").select(
        "objectid",
        "title",
        pl.col("beginyear").alias("year"),
        "medium",
        pl.col("visualbrowserclassification").alias("type"),
    )
    objects_df
    return (objects_df,)


@app.cell(hide_code=True)
def constituent_records_context(mo):
    mo.md(r"""
    The `.select` expression narrows the table and renames the source columns
    used throughout the analysis. Polars expressions operate on columns, so the
    transformation stays declarative as the dataset grows.

    ### Constituents

    `constituents.csv` contains every person or organization associated with an
    artwork, including artists, curators, and collectors. We keep the display
    name and nationality needed for exploration.
    """)
    return


@app.cell
def constituent_records(pl, read_dataset):
    constituents_df = read_dataset("constituents.csv").select(
        "constituentid",
        pl.col("forwarddisplayname").alias("name"),
        pl.col("visualbrowsernationality").alias("nationality"),
    )
    constituents_df
    return (constituents_df,)


@app.cell(hide_code=True)
def published_images_context(mo):
    mo.md(r"""
    ### Published images

    `published_images.csv` maps artwork identifiers to published images. It
    includes a thumbnail URL, an
    [International Image Interoperability Framework (IIIF)](https://iiif.io/)
    identifier, and the `openaccess` flag used here as public-domain status.

    The source contains several image rows for some artworks. We select one
    image per artwork, preferring an open-access primary view with the earliest
    source sequence.
    """)
    return


@app.cell
def published_images(pl, read_dataset):
    _published_images = read_dataset("published_images.csv").select(
        pl.col("depictstmsobjectid").alias("objectid"),
        "uuid",
        pl.col("iiifthumburl").alias("thumburl"),
        "openaccess",
        "viewtype",
        "sequence",
    )
    published_images_df = (
        _published_images.with_columns(
            pl.when(pl.col("openaccess").fill_null(0) == 1)
            .then(0)
            .otherwise(1)
            .alias("access_rank"),
            pl.when(pl.col("viewtype").str.to_lowercase() == "primary")
            .then(0)
            .otherwise(1)
            .alias("view_rank"),
            pl.col("sequence").fill_null(1_000_000).alias("image_sequence"),
        )
        .sort("objectid", "access_rank", "view_rank", "image_sequence", "uuid")
        .group_by("objectid", maintain_order=True)
        .agg(
            pl.col("uuid").first(),
            pl.col("thumburl").first(),
            (pl.col("openaccess").fill_null(0) == 1).any().alias("public"),
        )
    )
    published_images_df
    return (published_images_df,)


@app.cell(hide_code=True)
def primary_artists_context(mo):
    mo.md(r"""
    ### Primary artists

    `objects_constituents.csv` represents the many-to-many relationship between
    artworks and their associated people or organizations. An artwork can have
    several constituent records.

    For this analysis, the artist with the earliest `displayorder` becomes the
    primary artist for each artwork.
    """)
    return


@app.cell
def primary_artists(pl, read_dataset):
    object_artist_df = (
        read_dataset(
            "objects_constituents.csv",
            quote_char='"',
            infer_schema_length=None,
        )
        .filter(pl.col("role").eq(pl.lit("artist")))
        .sort("displayorder")
        .group_by("objectid")
        .first()
        .select("objectid", "constituentid")
    )
    object_artist_df
    return (object_artist_df,)


@app.cell(hide_code=True)
def collection_join_context(mo):
    mo.md(r"""
    The Polars pipeline applies the relationship rule in five steps:

    - Filter the table to records whose role is `artist`.
    - Sort those records by `displayorder`.
    - Group the records by `objectid`.
    - Take the first artist in each group.
    - Keep the two identifiers required for the join.

    ### Putting it together

    The four prepared tables can now be joined into a single dataframe. The
    final selection drops the constituent identifier and retains the artwork,
    artist, image, classification, and public-domain fields used by the
    visualizations.
    """)
    return


@app.cell
def collection_dataset(
    constituents_df,
    object_artist_df,
    objects_df,
    pl,
    published_images_df,
):
    df = (
        objects_df.join(object_artist_df, on="objectid")
        .join(constituents_df, on="constituentid")
        .join(published_images_df, on="objectid")
        .filter(pl.col("type").is_not_null())
        .select(pl.exclude("constituentid"))
        .sort("public")
        .sort("year", descending=True, nulls_last=True)
    )
    df
    return (df,)


@app.cell(hide_code=True)
def classification_context(mo):
    mo.md(r"""
    ## Plotting

    The NGA portal supports detailed exploration of individual artworks. The
    unified dataframe lets us ask collection-level questions about artwork
    types, artists, dates, and public-domain status.

    `obs.view_from_code` binds the Polars dataframe to an Observable Plot
    program rendered in the notebook. We will start with the distribution of
    artwork classifications across the collection.
    """)
    return


@app.cell
def classification_bar_chart(df, obs):
    obs.view_from_code(
        """
        Plot.plot({
          width: 900,
          marginLeft: 50,
          x: { label: "Artwork type" },
          y: { grid: true, label: "Artworks" },
          color: { legend: true, label: "Image status" },
          marks: [
            Plot.barY(
              df,
              Plot.groupX(
                { y: "count" },
                {
                  x: "type",
                  sort: { x: "-y" },
                  fill: (d) => (d.public ? "Public domain" : "Copyrighted"),
                  tip: {
                    pointer: "x",
                    format: { x: true, fill: true, y: ",d" },
                  },
                },
              ),
            ),
          ],
        });
        """,
        variables={"df": df},
    )
    return


@app.cell(hide_code=True)
def classification_waffle_context(mo):
    mo.md(r"""
    Prints, drawings, and photographs make up most of the collection. Public
    domain status also varies by classification. Images of prints, drawings,
    sculptures, and paintings are mostly public domain, while photographs and
    portfolios are largely copyrighted.

    Observable Plot composes marks and encodings, which makes it possible to
    test another representation with a small change. Replacing the bars with
    `waffleY` units turns the same counts into a faceted waffle chart.
    """)
    return


@app.cell
def classification_waffle_chart(df, obs):
    obs.view_from_code(
        """
        Plot.plot({
          width: 900,
          marginLeft: 50,
          fx: { label: "Artwork type" },
          y: { label: "Artworks" },
          color: { legend: true, label: "Image status" },
          marks: [
            Plot.waffleY(
              df,
              Plot.groupZ(
                { y: "count" },
                {
                  fx: "type",
                  fill: (d) => (d.public ? "Public domain" : "Copyrighted"),
                  sort: { fx: "-y" },
                  unit: 300,
                  tip: {
                    format: { fx: true, fill: true, y: ",d" },
                  },
                },
              ),
            ),
            Plot.ruleY([0]),
          ],
        });
        """,
        variables={"df": df},
    )
    return


@app.cell(hide_code=True)
def artist_totals_context(mo):
    mo.md(r"""
    The waffle chart changes the mark and grouping fields while preserving the
    same public-domain comparison.

    Polars and Plot can also answer a more specific question: **Which artists
    have the most artwork in the collection?** We group by artist and
    public-domain status, count the works in each group, and plot the top 25.
    """)
    return


@app.cell
def artist_totals_chart(df, obs):
    artwork_totals_df = (
        df.group_by("name", "public")
        .len()
        .rename({"len": "name_count"})
        .sort("name_count", descending=True)
        .head(25)
    )

    obs.view_from_code(
        """
        Plot.plot({
          marginLeft: 200,
          x: { grid: true, label: "Artworks" },
          y: { label: "Artist" },
          color: { legend: true, label: "Image status" },
          marks: [
            Plot.barX(artwork_totals_df, {
              x: "name_count",
              y: "name",
              sort: { y: "-x" },
              fill: (d) => (d.public ? "Public domain" : "Copyrighted"),
              tip: {
                pointer: "y",
                format: { y: true, fill: true, x: ",d" },
              },
            }),
          ],
        });
        """,
        variables={"artwork_totals_df": artwork_totals_df},
    )
    return


@app.cell(hide_code=True)
def gallery_component_context(mo):
    mo.md(r"""
    [Robert Frank](https://en.wikipedia.org/wiki/Robert_Frank) has nearly twice
    as many works as the next artist. Entries such as **American 20th Century**
    and **German 15th Century** are collective attributions. Artists also tend
    to appear in one public-domain category, which suggests that rights were
    cleared for groups of works at once.

    ## A custom `Gallery` component

    Aggregate plots reveal the collection's shape. The image URLs support a
    more direct view of any filtered subset. `Gallery` combines HTML, CSS, and
    JavaScript in an Observable notebook view to render a responsive grid of
    artwork thumbnails.
    """)
    return


@app.cell
def gallery_component(obs, pl):
    def Gallery(objects_df: pl.DataFrame, size: int = 100) -> obs.NotebookView:
        return obs.Notebook(
            obs.html(
                """
                <style>
                  .nga-gallery {
                    display: grid;
                    gap: 4px;
                  }

                  .nga-gallery-item {
                    position: relative;
                    display: block;
                    aspect-ratio: 1;
                    overflow: hidden;
                    border-radius: 5px;
                  }

                  .nga-gallery-thumb {
                    display: block;
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                  }

                  .nga-gallery-public-domain {
                    position: absolute;
                    right: 3px;
                    bottom: 3px;
                    width: 20px;
                    height: 20px;
                    opacity: 0.6;
                  }
                </style>
                """
            ),
            obs.js(
                """
                html`
                  <div
                    class="nga-gallery"
                    style=${{
                      gridTemplateColumns: `repeat(auto-fill, minmax(${size}px, 1fr))`,
                    }}
                  >
                    ${objects_df.map(
                      ({ objectid, thumburl, title, public: publicDomain }) =>
                        html.fragment`
                          <a
                            class="nga-gallery-item"
                            href=${`https://www.nga.gov/collection/art-object-page.${encodeURIComponent(objectid)}.html`}
                            title=${title}
                            target="_blank"
                          >
                            <img
                              class="nga-gallery-thumb"
                              src=${thumburl}
                              alt=${title ?? ""}
                              loading="lazy"
                              decoding="async"
                            >

                            ${
                              publicDomain
                                ? html`
                                  <img
                                    class="nga-gallery-public-domain"
                                    src="https://mirrors.creativecommons.org/presskit/icons/zero.svg"
                                    alt="Public domain"
                                    width="20"
                                    height="20"
                                  >
                                `
                                : null
                            }
                          </a>
                        `,
                    )}
                  </div>
                `
                """
            ),
            variables={
                "objects_df": objects_df,
                "size": size,
            },
        ).view()

    return (Gallery,)


@app.cell(hide_code=True)
def collection_gallery_context(mo):
    mo.md(r"""
    `Gallery` accepts a Polars dataframe and a thumbnail size. Each image links
    to its NGA collection page, and public-domain works carry a CC0 icon.

    A deterministic sample gives us a visual cross-section of the full
    collection.
    """)
    return


@app.cell
def collection_gallery(Gallery, df):
    Gallery(df.sample(20, seed=7))
    return


@app.cell(hide_code=True)
def timeline_context(mo):
    mo.md(r"""
    The same component can render any filtered dataframe, which gives us a
    reusable way to inspect the records behind an aggregate pattern.

    ## A closer look

    The first plots summarized artists and artwork types. We will now examine
    when the works were created. A stacked histogram shows artwork types over
    time and separates public-domain images from copyrighted images.
    """)
    return


@app.cell
def collection_timeline_chart(df, obs):
    obs.view_from_code(
        """
        Plot.plot({
          x: { label: "Year" },
          y: { grid: true, label: "Artworks" },
          fy: { label: "Image status" },
          color: { legend: true, label: "Artwork type" },
          marks: [
            Plot.rectY(
              df.filter((r) => r.year > 1401), // 15th century or later
              Plot.binX(
                { y: "count" },
                {
                  x: (d) => new Date(d.year, 0, 1),
                  fill: "type",
                  fy: (d) => (d.public ? "Public domain" : "Copyrighted"),
                  tip: {
                    pointer: "x",
                    format: {
                      x: (d) => d.getFullYear(),
                      fill: true,
                      fy: true,
                      y: ",d",
                    },
                  },
                },
              ),
            ),
            Plot.ruleY([0]),
          ],
          marginLeft: 100,
          marginRight: 100,
          width: 1000,
          height: 400,
        });
        """,
        variables={"df": df},
    )
    return


@app.cell(hide_code=True)
def notable_period_context(mo):
    mo.md(r"""
    The two distributions are noticeably different. Nearly all copyrighted
    works appear after 1850. Public-domain artworks are spread more evenly over
    time, apart from a sharp spike in drawings around the 1940s.

    Are these drawings associated with one artist or a wider event? We will
    filter the public-domain records to the years from 1925 through 1955.
    """)
    return


@app.cell
def notable_period_chart(df, obs, pl):
    notable_period_df = (
        df.filter("public")
        .filter(pl.col("year").gt(pl.lit(1925)))
        .filter(pl.col("year").lt(pl.lit(1955)))
        .sort("year")
    )
    obs.view_from_code(
        """
        Plot.plot({
          x: { label: "Year" },
          y: { grid: true, label: "Artworks" },
          color: { legend: true, label: "Artwork type" },
          marks: [
            Plot.rectY(
              notable_period_df,
              Plot.binX(
                { y: "count" },
                {
                  x: (d) => new Date(d.year, 0, 1),
                  fill: "type",
                  tip: {
                    pointer: "x",
                    format: {
                      x: (d) => d.getFullYear(),
                      fill: true,
                      y: ",d",
                    },
                  },
                },
              ),
            ),
          ],
        });
        """,
        variables={"notable_period_df": notable_period_df},
    )
    return (notable_period_df,)


@app.cell(hide_code=True)
def index_drawings_context(mo):
    mo.md(r"""
    Almost all of the spike falls within a narrower window from **1935 through
    1942**. That window contains roughly 18,000 individual drawings:
    """)
    return


@app.cell
def index_drawing_count(notable_period_df, pl):
    total_number_of_drawings = (
        notable_period_df.filter(pl.col("year").gt(pl.lit(1934)))
        .filter(pl.col("year").lt(pl.lit(1943)))
        .height
    )

    total_number_of_drawings
    return (total_number_of_drawings,)


@app.cell(hide_code=True)
def index_artists_context(mo):
    mo.md(r"""
    Those drawings were made by more than 1,000 artists:
    """)
    return


@app.cell
def index_artist_count(notable_period_df, pl):
    number_of_artists = (
        notable_period_df.filter(pl.col("year").gt(pl.lit(1934)))
        .filter(pl.col("year").lt(pl.lit(1943)))
        .group_by("name")
        .len()
        .height
    )

    number_of_artists
    return (number_of_artists,)


@app.cell(hide_code=True)
def index_gallery_context(mo):
    mo.md(r"""
    The concentration spans many artists, which points to a shared program or
    collection. A gallery sample lets us inspect the works themselves.
    """)
    return


@app.cell
def index_gallery(Gallery, notable_period_df):
    Gallery(notable_period_df.sample(50, seed=11))
    return


@app.cell(hide_code=True)
def index_finding(mo):
    mo.md(r"""
    Despite coming from many artists, the sampled works share a similar style
    and medium. Their metadata identifies the
    [Index of American Design](https://www.nga.gov/artworks/index-american-design).

    The Index contains 18,257 watercolor renderings created from **1935 through
    1942** as part of the Federal Art Project, a work-relief program. Artists
    documented textiles, woodcarvings, weathervanes, and other objects from
    across the United States. The National Gallery of Art became the home of
    this visual archive.

    The pattern in the dataframe traces a public art program funded during the
    Great Depression.
    """)
    return


@app.cell
def studio_view_data(
    df,
    notable_period_df,
    number_of_artists,
    pl,
    total_number_of_drawings,
):
    studio_artworks = (
        df.filter(pl.col("thumburl").is_not_null())
        .select("objectid", "title", "year", "name", "type", "thumburl", "public")
        .sort(
            ["public", "year", "objectid"],
            descending=[True, True, False],
            nulls_last=True,
        )
        .head(72)
        .to_dicts()
    )

    studio_index_artworks = (
        notable_period_df.filter(pl.col("year").is_between(1935, 1942))
        .filter(pl.col("thumburl").is_not_null())
        .select("objectid", "title", "year", "name", "type", "thumburl", "public")
        .sort(["year", "objectid"])
        .head(24)
        .to_dicts()
    )

    studio_summary = {
        "artworks": df.height,
        "artists": df.select(pl.col("name").n_unique()).item(),
        "public_domain": df.filter(pl.col("public")).height,
        "index_drawings": total_number_of_drawings,
        "index_artists": number_of_artists,
    }
    return


@app.cell(hide_code=True)
def conclusion(mo):
    mo.md(r"""
    ## Conclusion

    This marimo notebook combines Polars transformations, Observable Plot
    charts, and a custom gallery to explore the NGA Open Access dataset. The
    collection-level views led from a spike in public-domain drawings to the
    Index of American Design, a federal art project from the 1930s.

    Python owns the data analysis while `pyobservablejs` renders the web-based
    charts and gallery in the same reactive document.
    """)
    return


@app.cell
def dataset_source(pl):
    from _nga_data import (
        DATASET_BASE_URL,
        DATASET_REVISION,
        dataset_url,
        prepare_dataset_paths,
    )
    from _nga_data import (
        read_dataset as _read_dataset,
    )

    _dataset_paths = prepare_dataset_paths()

    def read_dataset(filename: str, **options):
        return _read_dataset(pl, _dataset_paths, filename, **options)

    return (read_dataset,)


@app.cell
def imports():
    import marimo as mo
    import observablejs as obs
    import polars as pl

    return mo, obs, pl


if __name__ == "__main__":
    app.run()
