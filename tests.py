import requests
import json

endPoint = 'https://forex-api.coin.z.com/public'
path     = '/v1/symbols'

response = requests.get(endPoint + path)
print(json.dumps(response.json(), indent=2))

