import requests

# ruleid: proof.python-disabled-tls-verification
requests.get("https://example.test", verify=False)
