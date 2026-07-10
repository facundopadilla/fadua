"""Tests for app.results — append-only JSONL results log and idempotency.

Idempotency key: (form, ID_Cliente, content-hash). content_hash is
sha256 of the normalized record values (sorted). A prior SUBMITTED (or
SUBMIT_UNCONFIRMED) entry blocks re-processing of an unchanged record;
DRY_RUN_OK never blocks a future run (dry-run never counts as done); an
edited record (different hash) is processed again even after a prior
SUBMITTED.
"""

import json

import pytest

from app.results import already_done, append_result, blocking_status, content_hash


@pytest.fixture
def results_path(tmp_path):
    return tmp_path / "results.jsonl"


class TestContentHash:
    def test_deterministic_for_same_values(self):
        values = {"ID_Cliente": "FIAT-001", "Nombre_Cliente": "Carlos Mendoza"}
        assert content_hash(values) == content_hash(dict(values))

    def test_stable_regardless_of_key_order(self):
        a = {"ID_Cliente": "FIAT-001", "Nombre_Cliente": "Carlos Mendoza"}
        b = {"Nombre_Cliente": "Carlos Mendoza", "ID_Cliente": "FIAT-001"}
        assert content_hash(a) == content_hash(b)

    def test_different_for_different_values(self):
        a = {"ID_Cliente": "FIAT-001", "Nombre_Cliente": "Carlos Mendoza"}
        b = {"ID_Cliente": "FIAT-001", "Nombre_Cliente": "Carlos M. (edited)"}
        assert content_hash(a) != content_hash(b)

    def test_is_a_sha256_hex_digest(self):
        values = {"ID_Cliente": "FIAT-001"}
        result = content_hash(values)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestAppendAndReadResults:
    def test_append_result_writes_one_jsonl_line(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="abc123",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        lines = results_path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["form"] == "ventas"
        assert record["id_cliente"] == "FIAT-001"
        assert record["content_hash"] == "abc123"
        assert record["status"] == "SUBMITTED"
        assert record["detail"] == "ok"
        assert "ts" in record

    def test_append_result_is_append_only(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        append_result(
            results_path,
            form="mora",
            id_cliente="FIAT-002",
            content_hash_value="hash2",
            status="SKIPPED_REQUIRED_EMPTY",
            detail="Ultimo_Pago_Monto empty",
            evidence="runs/fiat-002.png",
        )
        lines = results_path.read_text().splitlines()
        assert len(lines) == 2


class TestIdempotency:
    def test_unseen_record_is_not_already_done(self, results_path):
        assert already_done(results_path, "ventas", "FIAT-001", "hash1") is False

    def test_submitted_record_blocks_future_run_with_same_hash(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        assert already_done(results_path, "ventas", "FIAT-001", "hash1") is True

    def test_dry_run_ok_never_blocks_a_future_run(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="DRY_RUN_OK",
            detail="dry run only",
            evidence=None,
        )
        assert already_done(results_path, "ventas", "FIAT-001", "hash1") is False

    def test_edited_record_with_different_hash_is_processed_again(
        self, results_path
    ):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        # Same form + id_cliente, but a different content_hash (record
        # was edited in the sheet) -> must NOT be considered done.
        assert already_done(results_path, "ventas", "FIAT-001", "hash2") is False

    def test_submitted_record_twice_same_hash_is_skipped_second_time(
        self, results_path
    ):
        # Simulates: run once, get SUBMITTED, run again unchanged.
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="samehash",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        assert already_done(results_path, "ventas", "FIAT-001", "samehash") is True
        # A second SUBMITTED append (simulating a resumed run that
        # somehow still processed it) must not change the fact that
        # it's already done for that exact hash.
        assert already_done(results_path, "ventas", "FIAT-001", "samehash") is True

    def test_different_form_same_id_is_independent(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        # Same ID_Cliente can exist in both VENTAS and MORA sheets —
        # idempotency must be scoped per form.
        assert already_done(results_path, "mora", "FIAT-001", "hash1") is False

    def test_no_results_file_yet_returns_false(self, tmp_path):
        missing_path = tmp_path / "does_not_exist.jsonl"
        assert already_done(missing_path, "ventas", "FIAT-001", "hash1") is False

    def test_skipped_status_never_blocks_a_future_run(self, results_path):
        append_result(
            results_path,
            form="mora",
            id_cliente="FIAT-002",
            content_hash_value="hash1",
            status="SKIPPED_REQUIRED_EMPTY",
            detail="empty required field",
            evidence=None,
        )
        assert already_done(results_path, "mora", "FIAT-002", "hash1") is False

    def test_corrupt_line_is_skipped_and_scan_continues(self, results_path):
        # A truncated/corrupt JSONL line (e.g. a crash mid-write) must
        # not raise and must not stop the scan from reaching a valid,
        # matching SUBMITTED line further down the file.
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-999",
            content_hash_value="unrelated-hash",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        with results_path.open("a", encoding="utf-8") as f:
            f.write('{"form": "ventas", "id_cliente": "FIAT-001", "content_ha\n')
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        assert already_done(results_path, "ventas", "FIAT-001", "hash1") is True


class TestSubmitUnconfirmedBlocksReprocessing:
    def test_submit_unconfirmed_blocks_a_future_run_with_same_hash(self, results_path):
        # specs.md: SUBMIT_UNCONFIRMED must be "marcado para revisión",
        # never silently re-run -- an earlier Enviar click may have
        # actually succeeded, so an automatic retry risks a real
        # duplicate submission on this domain.
        append_result(
            results_path,
            form="mora",
            id_cliente="FIAT-003",
            content_hash_value="hash1",
            status="SUBMIT_UNCONFIRMED",
            detail="no confirmation observed",
            evidence="runs/fiat-003-error.png",
        )
        assert already_done(results_path, "mora", "FIAT-003", "hash1") is True

    def test_blocking_status_reports_submit_unconfirmed_distinctly(self, results_path):
        append_result(
            results_path,
            form="mora",
            id_cliente="FIAT-003",
            content_hash_value="hash1",
            status="SUBMIT_UNCONFIRMED",
            detail="no confirmation observed",
            evidence=None,
        )
        assert (
            blocking_status(results_path, "mora", "FIAT-003", "hash1")
            == "SUBMIT_UNCONFIRMED"
        )

    def test_blocking_status_reports_submitted_distinctly(self, results_path):
        append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-001",
            content_hash_value="hash1",
            status="SUBMITTED",
            detail="ok",
            evidence=None,
        )
        assert (
            blocking_status(results_path, "ventas", "FIAT-001", "hash1") == "SUBMITTED"
        )

    def test_blocking_status_returns_none_when_nothing_blocks(self, results_path):
        assert blocking_status(results_path, "ventas", "FIAT-001", "hash1") is None

    def test_edited_record_after_submit_unconfirmed_is_processed_again(
        self, results_path
    ):
        # Same idempotency rule as SUBMITTED: a DIFFERENT content-hash
        # (edited row) is never blocked.
        append_result(
            results_path,
            form="mora",
            id_cliente="FIAT-003",
            content_hash_value="hash1",
            status="SUBMIT_UNCONFIRMED",
            detail="no confirmation observed",
            evidence=None,
        )
        assert already_done(results_path, "mora", "FIAT-003", "hash2") is False
