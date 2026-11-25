from violence_etl.exceptions.etl_exception import EtlException


class DownloadException(EtlException):
    """The source dataset could not be downloaded."""
