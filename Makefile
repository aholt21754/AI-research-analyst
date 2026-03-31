.PHONY: test build deploy invoke logs

test:
	pytest tests/unit/ -v

build:
	sam build

deploy: build
	sam deploy

invoke:
	sam local invoke DailyDigestFunction \
		--env-vars env.local.json

logs:
	sam logs -n DailyDigestFunction \
		--stack-name ai-research-analyst \
		--tail
