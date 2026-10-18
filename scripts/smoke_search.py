"""Exercise the real HTTP route; requires a running server and model credentials."""
import httpx

with httpx.Client(base_url='http://127.0.0.1:8000', timeout=250) as client:
    print('Health:', client.get('/health').status_code)
    response = client.post('/tasks/search', json={'message': 'Find all emails I sent today'})
    print('Search HTTP status:', response.status_code)
    if response.is_success:
        print('Distinct occurrences returned:', len(response.json()))
    else:
        print(response.text)
