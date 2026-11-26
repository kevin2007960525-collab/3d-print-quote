"""Tessellate a STEP model in millimetres before passing it to Bambu Studio."""
import os
from pathlib import Path
import sys
import sysconfig

OCP_PACKAGE = "cadquery-ocp-novtk==8.0.1.1.0"


def dependency_dir():
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".cache")
    version = f"{sys.implementation.cache_tag}-{sysconfig.get_platform()}-8.0.1.1.0"
    return root / "BambuQuoteBridge" / "step" / version


def load_ocp():
    if dependency_dir().is_dir():
        sys.path.insert(0, str(dependency_dir()))
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.StlAPI import StlAPI_Writer

    return BRepMesh_IncrementalMesh, IFSelect_RetDone, STEPControl_Reader, StlAPI_Writer


def convert(source, destination):
    mesh_shape, done, step_reader, stl_writer = load_ocp()
    reader = step_reader()
    if reader.ReadFile(str(source)) != done:
        raise ValueError("Invalid STEP file")
    reader.SetSystemLengthUnit(1.0)
    if reader.TransferRoots() == 0:
        raise ValueError("No transferable geometry in the STEP file")
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("Empty STEP model")
    mesh = mesh_shape(shape, 0.05, False, 0.15, True)
    if not mesh.IsDone():
        raise ValueError("Could not triangulate STEP surfaces")
    writer = stl_writer()
    writer.ASCIIMode = False
    if not writer.Write(shape, str(destination)) or destination.stat().st_size <= 84:
        raise ValueError("Could not export a nonempty mesh")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        load_ocp()
    elif len(sys.argv) == 3:
        convert(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        sys.exit("Usage: step_converter.py source.step destination.stl")
