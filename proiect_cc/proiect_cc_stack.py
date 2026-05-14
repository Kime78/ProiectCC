from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_sns as sns,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct

class ProiectCcStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Static Website S3 Bucket
        website_bucket = s3.Bucket(self, "WebsiteBucket",
            website_index_document="index.html",
            public_read_access=True,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                block_public_policy=False,
                ignore_public_acls=False,
                restrict_public_buckets=False
            ),
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # 2. Amazon Cognito for Accounts
        user_pool = cognito.UserPool(self, "UserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True)
        )
        user_pool_client = user_pool.add_client("AppClient",
            auth_flows=cognito.AuthFlow(admin_user_password=True, user_password=True)
        )

        # 3. DynamoDB Table for saved products
        products_table = dynamodb.Table(self, "ProductsTable",
            partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # 4. Amazon SNS for price drops
        sns_topic = sns.Topic(self, "PriceDropTopic",
            display_name="Price Drop Notifications"
        )

        # 5. Lambda Functions
        # Shared Lambda runtime and code directory
        lambda_kwargs = {
            "runtime": _lambda.Runtime.PYTHON_3_9,
            "code": _lambda.Code.from_asset("lambda"),
        }

        add_product_lambda = _lambda.Function(self, "AddProductLambda",
            handler="add_product.handler",
            environment={"TABLE_NAME": products_table.table_name},
            **lambda_kwargs
        )

        get_products_lambda = _lambda.Function(self, "GetProductsLambda",
            handler="get_products.handler",
            environment={"TABLE_NAME": products_table.table_name},
            **lambda_kwargs
        )

        delete_product_lambda = _lambda.Function(self, "DeleteProductLambda",
            handler="delete_product.handler",
            environment={"TABLE_NAME": products_table.table_name},
            **lambda_kwargs
        )

        scraper_lambda = _lambda.Function(self, "ScraperLambda",
            handler="scraper.handler",
            environment={
                "TABLE_NAME": products_table.table_name,
                "SNS_TOPIC_ARN": sns_topic.topic_arn
            },
            timeout=Duration.minutes(5),
            **lambda_kwargs
        )

        # Permissions
        products_table.grant_read_write_data(add_product_lambda)
        products_table.grant_read_data(get_products_lambda)
        products_table.grant_read_write_data(delete_product_lambda)
        products_table.grant_read_write_data(scraper_lambda)
        sns_topic.grant_publish(scraper_lambda)

        # 6. EventBridge Rule (trigger scraper every N hours, e.g., 6 hours)
        rule = events.Rule(self, "ScraperScheduleRule",
            schedule=events.Schedule.rate(Duration.hours(6))
        )
        rule.add_target(targets.LambdaFunction(scraper_lambda))

        # 7. API Gateway
        api = apigw.RestApi(self, "ProductsApi",
            rest_api_name="Products Service",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS
            )
        )

        # Setup Cognito Authorizer
        authorizer = apigw.CognitoUserPoolsAuthorizer(self, "ProductosAuthorizer",
            cognito_user_pools=[user_pool]
        )

        auth_kwargs = {
            "authorizer": authorizer,
            "authorization_type": apigw.AuthorizationType.COGNITO
        }

        # Routes
        # POST /product
        product_resource = api.root.add_resource("product")
        product_resource.add_method("POST", apigw.LambdaIntegration(add_product_lambda), **auth_kwargs)
        
        # DELETE /product/{id}
        product_id_resource = product_resource.add_resource("{id}")
        product_id_resource.add_method("DELETE", apigw.LambdaIntegration(delete_product_lambda), **auth_kwargs)

        # GET /products
        products_resource = api.root.add_resource("products")
        products_resource.add_method("GET", apigw.LambdaIntegration(get_products_lambda), **auth_kwargs)

