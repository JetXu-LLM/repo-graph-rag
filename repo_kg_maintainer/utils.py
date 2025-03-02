from datetime import datetime
import dateutil.parser
from zoneinfo import ZoneInfo
from typing import Union, Optional

def normalize_datetime(time_input: Union[str, datetime, None]) -> Optional[str]:
    """
    Normalize different datetime formats to UTC ISO 8601 string.
    
    Args:
        time_input: Input time that could be:
            - datetime object (with or without tzinfo)
            - ISO 8601 string
            - Common datetime string formats
            - Unix timestamp (string or float)
            - None
    
    Returns:
        str: Normalized UTC datetime in ISO 8601 format (e.g., '2024-12-14T16:10:59+00:00')
             or None if input is None or invalid
    
    Examples:
        >>> normalize_datetime("2024-12-14 16:10:59")
        '2024-12-14T16:10:59+00:00'
        >>> normalize_datetime("Sat, 14 Dec 2024 16:10:59 GMT")
        '2024-12-14T16:10:59+00:00'
        >>> normalize_datetime(1734567890)  # Unix timestamp
        '2024-12-14T16:10:59+00:00'
    """
    if time_input is None:
        return None

    try:
        # If input is already a datetime object
        if isinstance(time_input, datetime):
            dt = time_input
        # If input might be a unix timestamp
        elif isinstance(time_input, (int, float)) or (
            isinstance(time_input, str) and time_input.isdigit()
        ):
            try:
                dt = datetime.fromtimestamp(float(time_input), tz=ZoneInfo("UTC"))
                return dt.isoformat()
            except (ValueError, OSError):
                # If timestamp conversion fails, try parsing as string
                dt = dateutil.parser.parse(str(time_input))
        # For string inputs
        else:
            # Handle special cases where dateutil might fail
            time_str = str(time_input).strip()
            if not time_str:
                return None
            
            # Parse the datetime string
            dt = dateutil.parser.parse(time_str)
        
        # Ensure timezone awareness
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        
        # Convert to UTC
        dt_utc = dt.astimezone(ZoneInfo("UTC"))
        
        return dt_utc.isoformat()

    except (ValueError, TypeError, dateutil.parser.ParserError) as e:
        # Log error if needed
        # logger.error(f"Failed to parse datetime: {time_input}, error: {str(e)}")
        return None