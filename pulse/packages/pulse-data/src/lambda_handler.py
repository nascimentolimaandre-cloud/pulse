"""AWS Lambda entry point using Mangum adapter.

Mangum wraps the FastAPI ASGI app so it can handle
API Gateway / ALB events in a Lambda function.
"""

from mangum import Mangum

from src.main import app

handler = Mangum(app, lifespan="off")
