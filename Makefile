PYTHON_LINTER := flake8
PYTHON_TEST_RUNNER := pytest
PYTHON_TYPE_CHECK := mypy --strict


INPUT_FILES := $(wildcard ./*.py ./**/*.py)
FILE ?= mogo/
TEST_FILE ?= tests/


test: lint typecheck typecheck-tests
	@$(PYTHON_TEST_RUNNER) tests/ --verbose


lint: $(INPUT_FILES)
	$(PYTHON_LINTER)


typecheck: $(INPUT_FILES)
	MYPYPATH=stubs $(PYTHON_TYPE_CHECK) $(FILE)


typecheck-tests: $(INPUT_FILES)
	MYPYPATH=stubs $(PYTHON_TYPE_CHECK) $(TEST_FILE)

.PHONY: test lint typecheck
