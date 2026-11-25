from violence_etl.exceptions.etl_exception import EtlException


class SchemaException(EtlException):
    """The source CSV header does not match the expected contract."""
