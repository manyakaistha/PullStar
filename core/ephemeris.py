"""
Star Trail Aligner - Ephemeris Module

Provides precise Polaris position calculation based on observer location and time.
Uses astropy for astronomical calculations.

This module is optional - the aligner works without it, but ephemeris data
can improve accuracy for very long sessions where Polaris moves measurably.

Note: astropy is a large dependency (~150MB). Install with:
    pip install astropy
"""

from datetime import datetime
from typing import Optional, Tuple, Union


def is_ephemeris_available() -> bool:
    """
    Check if astropy is installed and ephemeris calculations are available.
    
    Returns:
        True if astropy is available, False otherwise
    """
    try:
        import astropy
        return True
    except ImportError:
        return False


def get_polaris_position(
    timestamp: Union[datetime, str],
    latitude: float,
    longitude: float,
    altitude_m: float = 0.0
) -> Optional[Tuple[float, float]]:
    """
    Calculate Polaris position at given time and location.
    
    Polaris is not exactly at the celestial north pole - it orbits
    about 0.73° away. For very long star trail sessions (multiple hours),
    this can cause slight drift in the tracked position.
    
    Args:
        timestamp: Observation time (datetime object or ISO format string)
        latitude: Observer latitude in degrees (positive = North)
        longitude: Observer longitude in degrees (positive = East)
        altitude_m: Observer altitude above sea level in meters
        
    Returns:
        Tuple of (altitude_deg, azimuth_deg) or None if calculation fails
        - altitude_deg: Angle above horizon (0-90°)
        - azimuth_deg: Compass direction (0=N, 90=E, 180=S, 270=W)
    """
    try:
        from astropy.coordinates import EarthLocation, AltAz, SkyCoord
        from astropy.time import Time
        import astropy.units as u
        
        # Define observer location
        observer = EarthLocation(
            lat=latitude * u.deg,
            lon=longitude * u.deg,
            height=altitude_m * u.m
        )
        
        # Parse timestamp
        if isinstance(timestamp, str):
            obs_time = Time(timestamp, scale='utc')
        elif isinstance(timestamp, datetime):
            obs_time = Time(timestamp.isoformat(), scale='utc')
        else:
            obs_time = Time(timestamp, scale='utc')
        
        # Polaris coordinates (J2000 epoch, ICRS frame)
        # RA: 02h 31m 49.09s = 37.9545°
        # Dec: +89° 15' 50.8" = 89.2641°
        polaris = SkyCoord(
            ra=37.9545 * u.deg,
            dec=89.2641 * u.deg,
            frame='icrs'
        )
        
        # Transform to Alt-Az frame for this observer and time
        altaz_frame = AltAz(obstime=obs_time, location=observer)
        polaris_altaz = polaris.transform_to(altaz_frame)
        
        # Extract altitude and azimuth
        altitude = polaris_altaz.alt.deg
        azimuth = polaris_altaz.az.deg
        
        return (altitude, azimuth)
        
    except ImportError:
        # astropy not installed
        return None
    except Exception as e:
        # Any calculation error
        print(f"Warning: Ephemeris calculation failed: {e}")
        return None


def get_polaris_offset_from_pole(
    timestamp: Union[datetime, str],
    latitude: float,
    longitude: float
) -> Optional[Tuple[float, float]]:
    """
    Calculate Polaris offset from true celestial pole.
    
    This can be used to predict how much Polaris will drift
    relative to its position at the start of imaging.
    
    Args:
        timestamp: Observation time
        latitude: Observer latitude in degrees
        longitude: Observer longitude in degrees
        
    Returns:
        Tuple of (hour_angle_deg, offset_arcmin) or None if unavailable
        - hour_angle_deg: Current hour angle of Polaris
        - offset_arcmin: Angular distance from pole in arcminutes
    """
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u
        import numpy as np
        
        # Polaris coordinates
        polaris = SkyCoord(ra=37.9545 * u.deg, dec=89.2641 * u.deg, frame='icrs')
        
        # Calculate hour angle
        observer = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg)
        
        if isinstance(timestamp, str):
            obs_time = Time(timestamp, scale='utc')
        elif isinstance(timestamp, datetime):
            obs_time = Time(timestamp.isoformat(), scale='utc')
        else:
            obs_time = Time(timestamp, scale='utc')
        
        # Local sidereal time
        lst = obs_time.sidereal_time('apparent', longitude * u.deg)
        
        # Hour angle = LST - RA
        hour_angle = (lst - polaris.ra).deg
        if hour_angle > 180:
            hour_angle -= 360
        elif hour_angle < -180:
            hour_angle += 360
        
        # Polaris offset from pole (90° - declination, in arcminutes)
        offset_arcmin = (90.0 - 89.2641) * 60.0  # ~44.2 arcmin
        
        return (hour_angle, offset_arcmin)
        
    except ImportError:
        return None
    except Exception:
        return None


def estimate_polaris_drift_pixels(
    start_time: Union[datetime, str],
    end_time: Union[datetime, str],
    latitude: float,
    longitude: float,
    focal_length_mm: float,
    sensor_width_mm: float,
    image_width_pixels: int
) -> Optional[float]:
    """
    Estimate how many pixels Polaris will drift during an imaging session.
    
    This helps determine if ephemeris correction is necessary.
    For short sessions (<1 hour), drift is usually negligible.
    
    Args:
        start_time: Session start time
        end_time: Session end time
        latitude: Observer latitude
        longitude: Observer longitude
        focal_length_mm: Lens focal length in mm
        sensor_width_mm: Camera sensor width in mm
        image_width_pixels: Image width in pixels
        
    Returns:
        Estimated drift in pixels, or None if calculation fails
    """
    try:
        import numpy as np
        
        # Get Polaris positions at start and end
        pos_start = get_polaris_position(start_time, latitude, longitude)
        pos_end = get_polaris_position(end_time, latitude, longitude)
        
        if pos_start is None or pos_end is None:
            return None
        
        alt_start, az_start = pos_start
        alt_end, az_end = pos_end
        
        # Calculate angular change (simplified for small angles)
        d_alt = alt_end - alt_start
        d_az = (az_end - az_start) * np.cos(np.radians(alt_start))
        
        angular_change_deg = np.sqrt(d_alt**2 + d_az**2)
        
        # Convert to pixels
        # Field of view = 2 * atan(sensor_width / (2 * focal_length))
        fov_deg = 2 * np.degrees(np.arctan(sensor_width_mm / (2 * focal_length_mm)))
        pixels_per_degree = image_width_pixels / fov_deg
        
        drift_pixels = angular_change_deg * pixels_per_degree
        
        return drift_pixels
        
    except Exception:
        return None
