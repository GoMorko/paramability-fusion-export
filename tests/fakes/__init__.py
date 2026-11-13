"""The fakes the tests share, by domain: the parameter store (`store`), the export ports (`port`), Fusion objects for
the reader tests (`design`) and the dialog inputs (`dialog`). The store and the ports have every member of the
declared interfaces (`tests/test_interfaces.py`)."""
from tests.fakes.design import (FakeBRepManager, FakeBooleanTypes, FakeCellBody, FakeCollection, FakeDesign, FakeEdge,
                                FakeEntity, FakeFace, FakeItem, FakeMadeFeature, FakeMarkerTimeline, FakeMatrix3D,
                                FakeOccurrence, FakeParam, FakeReachDesign, FakeSolid, FakeSolidBody, FakeTimeline,
                                FakeTimelineItem, IDENTITY, Vec, apply_matrix, compose_matrices, fake_brep_tools,
                                turn_x, turn_z)
from tests.fakes.dialog import (FakeCheckbox, FakeCommand, FakeDropDown, FakeInput, FakeInputs, FakeListItems,
                                FakeSelection, FakeStringInput, FakeTable, FakeTextBox, install_adsk_core)
from tests.fakes.port import BOX, FakePartsPort, FakePort, first_read, shifted
from tests.fakes.store import FakeStore, RollingStore, TrimStore
