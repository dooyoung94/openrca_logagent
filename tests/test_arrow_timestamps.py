import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from logagent_bench.adapter import iter_records


class ArrowTimestampContract(unittest.TestCase):
    def test_source_temporal_units_and_nulls_become_exact_integer_nanoseconds(self):
        values = {"ns": 1777726745596953894, "us": 1777726745596953,
                  "ms": 1777726745596, "s": 1777726745}
        table = pa.table({unit: pa.array([value, None], type=pa.timestamp(unit))
                          for unit, value in values.items()})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timestamps.parquet"
            pq.write_table(table, path)
            records = list(iter_records(path))
        for unit, value in values.items():
            factor = {"ns": 1, "us": 1000, "ms": 10**6, "s": 10**9}[unit]
            self.assertIsInstance(records[0][unit], int)
            self.assertEqual(records[0][unit], value*factor)
            self.assertIsNone(records[1][unit])


if __name__ == "__main__":
    unittest.main()
