import unittest

from src.shared.extraction.multiple_reference_expander import expand_multiple_references
from src.utils.post_processing import _prepare_reference_for_mongo


class TestMongoReferenceOutput(unittest.TestCase):
    def test_mongo_reference_uses_raw_inclusive_offsets_and_identifier_information(self):
        tail = {
            "khoan": {
                "information": "khoản 5",
                "position_start": 2,
                "position_end": 9,
                "_raw_position_start": 100,
                "_raw_position_end": 106,
            },
            "dieu": {
                "information": "Điều 8a",
                "position_start": 10,
                "position_end": 17,
                "_raw_position_start": 120,
                "_raw_position_end": 126,
            },
            "nghidinh": {
                "information": "Nghị định số 01/2026/NĐ-CP",
                "position_start": 20,
                "position_end": 47,
                "_raw_position_start": 140,
                "_raw_position_end": 166,
            },
        }

        prepared = _prepare_reference_for_mongo(tail)

        self.assertEqual(prepared["khoan"]["information"], "5")
        self.assertEqual(prepared["dieu"]["information"], "8a")
        self.assertEqual(prepared["nghidinh"]["information"], "Nghị định số 01/2026/NĐ-CP")
        self.assertEqual(prepared["khoan"]["position_start"], 100)
        self.assertEqual(prepared["khoan"]["position_end"], 106)
        self.assertNotIn("_raw_position_start", prepared["khoan"])

    def test_mongo_reference_falls_back_to_inclusive_integer_end(self):
        prepared = _prepare_reference_for_mongo(
            {
                "diem": {
                    "information": "điểm c",
                    "position_start": 4,
                    "position_end": 10,
                }
            }
        )

        self.assertEqual(prepared["diem"]["information"], "c")
        self.assertEqual(prepared["diem"]["position_end"], 9)

    def test_multiple_reference_expansion_does_not_use_fractional_positions(self):
        expanded = expand_multiple_references([
            {
                "khoan": {
                    "information": "khoản 1, 2, 3",
                    "position_start": 10,
                    "position_end": 23,
                    "_raw_position_start": 100,
                    "_raw_position_end": 112,
                },
                "dieu": {
                    "information": "Điều 8",
                    "position_start": 30,
                    "position_end": 36,
                },
            }
        ])

        self.assertEqual(len(expanded), 3)
        for reference in expanded:
            value = reference["khoan"]
            self.assertIs(type(value["position_start"]), int)
            self.assertIs(type(value["position_end"]), int)
            self.assertIs(type(value["_raw_position_start"]), int)
            self.assertIs(type(value["_raw_position_end"]), int)


if __name__ == "__main__":
    unittest.main()
