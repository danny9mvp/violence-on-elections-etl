from violence_etl.exceptions.etl_exception import EtlException


class LoadException(EtlException):
    """A layer failed while writing to the warehouse."""
