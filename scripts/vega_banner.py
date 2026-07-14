from dataclasses import dataclass

try:
    from version import APP_NAME, APP_SUBTITLE, VERSION
except ImportError:
    from scripts.version import APP_NAME, APP_SUBTITLE, VERSION


@dataclass
class VegaStatus:
    model: str = "vega-core"
    internet: bool = False
    version: str = VERSION


def render_banner(status: VegaStatus) -> str:
    internet_status = "ON" if status.internet else "OFF"
    return "\n".join([
        f"{APP_NAME} {status.version}",
        APP_SUBTITLE,
        f"Model: {status.model}",
        f"Internet: {internet_status}",
        "Status: Ready",
    ])


if __name__ == "__main__":
    print(render_banner(VegaStatus()))
