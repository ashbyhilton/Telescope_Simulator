from telescope_simulator.model.fit_data import FitDataPoint
from telescope_simulator.model.project import Project, default_demo_project


def test_round_trip_includes_fit_data_points():
    project = default_demo_project()
    project.fit_data_points = [
        FitDataPoint(z_mm=10.0, diameter_mm=1.0),
        FitDataPoint(z_mm=None, diameter_mm=None),
    ]

    restored = Project.from_dict(project.to_dict())

    assert len(restored.fit_data_points) == 2
    assert restored.fit_data_points[0].z_mm == 10.0
    assert restored.fit_data_points[0].diameter_mm == 1.0
    assert restored.fit_data_points[1].z_mm is None


def test_old_save_file_without_fit_data_key_defaults_to_four_empty_rows():
    project = default_demo_project()
    d = project.to_dict()
    del d["fit_data_points"]  # simulate a save file from before this field existed

    restored = Project.from_dict(d)

    assert len(restored.fit_data_points) == 4
    assert all(not p.is_valid() for p in restored.fit_data_points)


def test_user_clearing_all_rows_is_respected_not_reset_to_defaults():
    project = default_demo_project()
    project.fit_data_points = []  # key present, genuinely empty

    restored = Project.from_dict(project.to_dict())

    assert restored.fit_data_points == []


def test_round_trip_includes_v2_raytrace_config_fields():
    project = default_demo_project()
    project.config.raytrace_enabled = True
    project.config.ambient_index = 1.33
    project.config.raytrace_ray_count = 15

    restored = Project.from_dict(project.to_dict())

    assert restored.config.raytrace_enabled is True
    assert restored.config.ambient_index == 1.33
    assert restored.config.raytrace_ray_count == 15


def test_old_save_file_without_raytrace_keys_defaults_to_disabled_air():
    project = default_demo_project()
    d = project.to_dict()
    for key in ("raytrace_enabled", "ambient_index", "raytrace_ray_count"):
        del d["config"][key]  # simulate a save file from before v2.0

    restored = Project.from_dict(d)

    assert restored.config.raytrace_enabled is False
    assert restored.config.ambient_index == 1.0
    assert restored.config.raytrace_ray_count == 21
