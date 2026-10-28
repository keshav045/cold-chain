# All targets work without installing the package (PYTHONPATH=src).
PY ?= python3
CC = PYTHONPATH=src $(PY) -m coldchain
SEED ?= 20261022

.PHONY: install generate generate-starter generate-full validate test reproduce reproduce-full docs all clean

install:
	$(PY) -m pip install -r requirements.txt

generate: generate-full            ## the 1,000-shipment / 300-container dataset

generate-full:
	$(CC) generate --scale full --seed $(SEED) --out data/full

generate-starter:
	$(CC) generate --scale starter --seed $(SEED) --out data/starter

validate:                           ## re-validate whatever is already in data/full
	$(CC) validate --data data/full --write

test:
	PYTHONPATH=src $(PY) -m pytest -q

reproduce:                          ## generate twice (starter scale), compare row counts + SHA-256
	$(CC) reproduce --scale starter --out build/repro

reproduce-full:
	$(CC) reproduce --scale full --out build/repro-full

docs:
	$(CC) docs --out docs

all: test generate-starter generate-full reproduce

clean:
	rm -rf build .pytest_cache
