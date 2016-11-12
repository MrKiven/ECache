clear_pyc:
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -delete

pylint:
	flake8 ecache
	bash tools/scripts/ci.sh

unittest: pylint
	mkdir -p .build
	py.test tests --junitxml=.build/unittest.xml --cov ecache --cov-report xml -n 4

tag:
	@t=`python setup.py  --version`;\
	echo v$$t; git tag v$$t
