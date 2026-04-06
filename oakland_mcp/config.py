import os
from dotenv import load_dotenv

load_dotenv()

SOCRATA_DOMAIN = os.getenv("SOCRATA_DOMAIN", "data.oaklandca.gov")
SOCRATA_APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")
DISCOVERY_API_BASE = "https://api.us.socrata.com/api/catalog/v1"
SODA_BASE = f"https://{SOCRATA_DOMAIN}/resource"
METADATA_BASE = f"https://{SOCRATA_DOMAIN}/api/views"

MAX_LIMIT = 5000
DEFAULT_QUERY_LIMIT = 500
DEFAULT_PREVIEW_LIMIT = 10
DEFAULT_SEARCH_LIMIT = 10
REQUEST_TIMEOUT = 30.0
