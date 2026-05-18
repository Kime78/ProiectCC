from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    CfnOutput,
    aws_s3 as s3,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_sns as sns,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_logs as logs,
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
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True) # Tells Cognito to actually send the email verification code
        )
        user_pool_client = user_pool.add_client("AppClient",
            auth_flows=cognito.AuthFlow(
                admin_user_password=True, 
                user_password=True,
                user_srp=True # Required by AWS Amplify for secure password transmission
            )
        )

        # 3. DynamoDB Table for saved products
        products_table = dynamodb.Table(self, "ProductsTable",
            partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # 4. Email Sender (SES requires verifying this email in the AWS Console)
        # You will need to change this to the email address you verify in AWS SES
        verified_sender_email = "aimaster610@gmail.com"

        # 5. Lambda Functions
        # Shared Lambda runtime and code directory
        lambda_kwargs = {
            "runtime": _lambda.Runtime.PYTHON_3_9,
            "code": _lambda.Code.from_asset("lambda"),
        }

        # The new Scraper Lambda (replaces Fargate fully)
        scraper_lambda = _lambda.Function(self, "ScraperLambda",
            handler="scraper.handler",
            environment={
                "TABLE_NAME": products_table.table_name,
                "SENDER_EMAIL": verified_sender_email
            },
            timeout=Duration.minutes(3), # generous timeout just in case
            **lambda_kwargs
        )

        add_product_lambda = _lambda.Function(self, "AddProductLambda",
            handler="add_product.handler",
            environment={
                "TABLE_NAME": products_table.table_name,
                "SCRAPER_FUNCTION_NAME": scraper_lambda.function_name
            },
            **lambda_kwargs
        )

        get_products_lambda = _lambda.Function(self, "GetProductsLambda",
            handler="get_products.handler",
            environment={
                "TABLE_NAME": products_table.table_name,
            },
            **lambda_kwargs
        )

        check_product_lambda = _lambda.Function(self, "CheckProductLambda",
            handler="check_product.handler",
            environment={
                "TABLE_NAME": products_table.table_name,
                "SCRAPER_FUNCTION_NAME": scraper_lambda.function_name
            },
            **lambda_kwargs
        )

        delete_product_lambda = _lambda.Function(self, "DeleteProductLambda",
            handler="delete_product.handler",
            environment={"TABLE_NAME": products_table.table_name},
            **lambda_kwargs
        )

        # Permissions
        products_table.grant_read_write_data(scraper_lambda)
        products_table.grant_read_write_data(add_product_lambda)
        products_table.grant_read_data(get_products_lambda)
        products_table.grant_read_write_data(check_product_lambda)
        products_table.grant_read_write_data(delete_product_lambda)
        
        # Grant lambdas to invoke the scraper manually
        scraper_lambda.grant_invoke(add_product_lambda)
        scraper_lambda.grant_invoke(check_product_lambda)
        
        # Grant SES SendEmail permission to Scraper Lambda
        scraper_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=["*"]
        ))

        # 6. EventBridge Rule (trigger scraper every N hours, e.g., 6 hours)
        rule = events.Rule(self, "ScraperScheduleRule",
            schedule=events.Schedule.rate(Duration.minutes(1))
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

        # POST /product/{id}/check
        product_check_resource = product_id_resource.add_resource("check")
        product_check_resource.add_method("POST", apigw.LambdaIntegration(check_product_lambda), **auth_kwargs)

        # GET /products
        products_resource = api.root.add_resource("products")
        products_resource.add_method("GET", apigw.LambdaIntegration(get_products_lambda), **auth_kwargs)

        # 8. CloudFront Distribution (HTTPS)
        # Using S3 Static Website Endpoint as the origin
        distribution = cloudfront.Distribution(self, "WebsiteDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    website_bucket.bucket_website_domain_name,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
            )
        )

        # 9. Outputs for the Frontend
        CfnOutput(self, "WebsiteBucketName", value=website_bucket.bucket_name)
        CfnOutput(self, "WebsiteURL", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "ApiUrl", value=api.url)

