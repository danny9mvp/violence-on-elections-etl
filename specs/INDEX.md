| Feature ID | Feature Name | Description |
| --- | --- | --- |
| 0001 | KeyVaultIntegration | Split generic Azure Key Vault access from PostgreSQL configuration and move URL building into settings |
| 0002 | AzureBlobStorageIntegration | Integrate Azure Blob Storage for bronze and gold CSV artifacts in PROD while keeping local data directory behavior in DEV/TEST |
| 0003 | DockerContainerization | Dockerize the ETL for local DEV runs and monthly Azure Container Apps Job execution with runtime-only image, non-root user, and mounted local persistence |
