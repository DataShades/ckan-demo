"""Record demo videos of CKAN portals and extensions from Python scenarios."""

from ckan_demo.director import Director, Options
from ckan_demo.portal import Portal, PortalError, exists
from ckan_demo.scenario import DEFAULT_PASSWORD, Scenario, Scene, User, load_scenario
from ckan_demo.seeding import Setup

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_PASSWORD",
    "Director",
    "Options",
    "Portal",
    "PortalError",
    "Scenario",
    "Scene",
    "Setup",
    "User",
    "exists",
    "load_scenario",
]
