# Geoname -> population pipeline. Pure stdlib Python 3.10+; no pip install.
PY ?= python3

.PHONY: all points census municipal boundaries districts province municipalities join shortlist exclude-nested basins basin-report test clean clean-all progress

all: points census municipal boundaries districts province municipalities join shortlist exclude-nested basins

points:            ## fetch a coordinate per Geonames.csv row (resumable)
	$(PY) 01_fetch_points.py --workers 6

census:            ## extract 2021 population from the Census Profile CSV
	$(PY) 02_census_pop.py

municipal:         ## extract BC Stats estimates for the 162 municipalities
	$(PY) 02b_municipal_est.py

boundaries:        ## download DA + CSD boundaries from StatCan (~353 MB)
	$(PY) 03_fetch_boundaries.py

districts:         ## download BC's 29 regional districts from DataBC (~20 MB)
	$(PY) 03b_fetch_districts.py

province:          ## download BC's provincial boundary from DataBC (~1.5 MB)
	$(PY) 03c_fetch_province.py

municipalities:    ## download BC's 160 municipal boundaries from DataBC (~4 MB)
	$(PY) 03d_fetch_municipalities.py

join:              ## produce out/geoname_population.csv
	$(PY) 04_join.py

shortlist:         ## reduce to out/geoname_shortlist.csv (primary, non-trivial)
	$(PY) 05_shortlist.py

exclude-nested:    ## drop shortlisted places inside a municipality's legal boundary
	$(PY) 05b_exclude_nested_municipalities.py

basins:            ## group every place into a commute basin for the selector
	$(PY) 06_basins.py

basin-report:      ## every basin's members, farthest from the hub first
	$(PY) 06_basins.py --report

test:              ## projection, geometry, parsing and output checks
	$(PY) test_pipeline.py

progress:          ## how far the point fetch has got
	@wc -l < data/geoname_points.jsonl | xargs echo "cached points:"
	@tail -1 data/fetch.log 2>/dev/null || true

clean:             ## remove outputs, keep the fetched cache
	rm -rf out

clean-all: clean   ## also drop the API cache and downloads
	rm -rf data
