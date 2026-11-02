# QAmbit: development helpers.
PLUGIN = qambit
PROFILE ?= default
PLUGINS_DIR = $(HOME)/.local/share/QGIS/QGIS3/profiles/$(PROFILE)/python/plugins
SOURCES = $(shell find . -name '*.py' -not -path './tests/*')
LANGUAGES = fr
TS = $(LANGUAGES:%=i18n/$(PLUGIN)_%.ts)
QM = $(TS:.ts=.qm)
PYLUPDATE ?= $(shell command -v pylupdate6 || command -v pylupdate5)
LRELEASE ?= $(shell command -v lrelease-qt6 || command -v lrelease || command -v lrelease-qt5)

.PHONY: deploy undeploy ts qm test lint zip

# Links the working tree into the QGIS profile, so a plugin reload picks up edits.
deploy: qm
	mkdir -p $(PLUGINS_DIR)
	ln -sfn $(CURDIR) $(PLUGINS_DIR)/$(PLUGIN)

undeploy:
	rm -f $(PLUGINS_DIR)/$(PLUGIN)

# Updates the translation sources from the code.
ts:
	$(PYLUPDATE) --ts $(TS) $(SOURCES)

qm: $(QM)

i18n/%.qm: i18n/%.ts
	$(LRELEASE) $< -qm $@

test:
	QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests

lint:
	ruff check .
	ruff format --check .

# A package for "Install from ZIP".
zip: qm
	rm -f $(PLUGIN).zip
	cd .. && zip -qr $(PLUGIN)/$(PLUGIN).zip $(PLUGIN) \
	    -x '$(PLUGIN)/.git*' '*/__pycache__/*' '$(PLUGIN)/tests/*' '$(PLUGIN)/*.zip' '$(PLUGIN)/i18n/*.ts' '$(PLUGIN)/Makefile' '$(PLUGIN)/ruff.toml' '$(PLUGIN)/*.png'
