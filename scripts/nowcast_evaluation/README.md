# Nowcast evaluation (regime map NOW point)

Produces the numbers archived in `config/nowcast_evaluation.json`. Raw downloads
go in a directory of their own (`RAW`), never in the repository.

1. Download into `RAW`: Cleveland Fed `nowcast_year.json` (inflation nowcasting
   chart data), Philadelphia Fed `ADS_All_Vintages-zip.zip` (unzipped).
2. `python ads_convert.py RAW/ADS_All_Vintages-zip.xlsx RAW/ads_vintages.parquet`
3. `python cle_parse.py RAW/cle_nowcast_year.json RAW/cle_year.parquet`
4. `python alfred_pull.py RAW` (needs `FRED_API_KEY`, read the same way as `sources/alfred.py`)
5. `python evaluate.py RAW OUT` then `python evaluate2.py RAW OUT`
