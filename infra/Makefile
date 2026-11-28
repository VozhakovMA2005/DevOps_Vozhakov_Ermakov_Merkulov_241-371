.PHONY: check check-secrets

check: check-secrets
	ANSIBLE_INVENTORY_UNPARSED_FAILED=true ansible-inventory --graph
	ansible-playbook --syntax-check site.yml

check-secrets:
	python3 -B scripts/check_secrets.py
