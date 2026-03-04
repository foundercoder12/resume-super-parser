from __future__ import annotations


class ResumeParserError(Exception):
    """Base error for all pipeline errors."""
    error_code: str = "PARSE_ERROR"

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        if error_code:
            self.error_code = error_code


class InvalidFileError(ResumeParserError):
    error_code = "INVALID_FILE"


class FileTooLargeError(ResumeParserError):
    error_code = "FILE_TOO_LARGE"


class EncryptedPdfError(ResumeParserError):
    error_code = "ENCRYPTED_PDF"


class PdfExtractionError(ResumeParserError):
    error_code = "PDF_EXTRACTION_ERROR"


class OcrError(ResumeParserError):
    error_code = "OCR_ERROR"


class LlmExtractionError(ResumeParserError):
    error_code = "LLM_EXTRACTION_ERROR"


class StorageError(ResumeParserError):
    error_code = "STORAGE_ERROR"


class JobNotFoundError(ResumeParserError):
    error_code = "JOB_NOT_FOUND"
