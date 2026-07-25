"""
Tests fuer die Totale-Auswahl (Punkt 4, `totale_mode`). Deterministisch, ohne
Pipeline-Aufbau — getestet wird die reine Auswahl-Logik `_pick_totale`.

Aufruf:  python3 modules/multicam_cutter/test_totale_mode.py
oder:    pytest modules/multicam_cutter/test_totale_mode.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                    # modules/multicam_cutter/ (frame_utils etc.)
sys.path.insert(0, os.path.dirname(HERE))   # modules/
from add_reactions_to_edl import _pick_totale  # noqa: E402

W3 = [{'name': 'T1'}, {'name': 'T2'}, {'name': 'T3'}]


def test_round_robin_cycles():
    """round_robin geht reihum und zaehlt ueber Aufrufe (Sections) hinweg weiter."""
    st = {}
    picks = [_pick_totale(W3, 'round_robin', st)['name'] for _ in range(7)]
    assert picks == ['T1', 'T2', 'T3', 'T1', 'T2', 'T3', 'T1'], picks


def test_first_and_single_are_byte_identical():
    """mode='first' sowie 0/1 Totale ergeben IMMER die erste — altes Verhalten."""
    st = {}
    assert [_pick_totale(W3, 'first', st)['name'] for _ in range(5)] == ['T1'] * 5
    assert _pick_totale([{'name': 'T1'}], 'round_robin', {})['name'] == 'T1'
    assert _pick_totale([{'name': 'T1'}], 'random', {})['name'] == 'T1'
    assert _pick_totale([], 'round_robin', {}) is None


def test_random_is_reproducible_and_varies():
    """random ist mit festem Seed reproduzierbar, rotiert aber wirklich."""
    def seq():
        st = {}
        return [_pick_totale(W3, 'random', st)['name'] for _ in range(10)]
    assert seq() == seq(), "fester Seed -> reproduzierbar"
    assert len(set(seq())) > 1, "sollte wirklich rotieren"


if __name__ == "__main__":
    tests = [test_round_robin_cycles,
             test_first_and_single_are_byte_identical,
             test_random_is_reproducible_and_varies]
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
    print(f"\n{len(tests)} Tests grün.")
