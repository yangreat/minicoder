# CSV Stats Bug (multi-file)

`parser.parse_csv` must respect quoted fields that contain commas. `stats.column_mean(text, col)` computes the mean of a 0-based numeric column and must skip blank cells. Run `pytest` to see failures.
