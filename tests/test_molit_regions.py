import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.molit_regions import parse_mois_legal_district_zip


class MoisLegalDistrictParserTest(unittest.TestCase):
    def test_selects_active_leaf_sgg_codes_and_excludes_parent_cities(self):
        text = "\n".join(
            [
                "법정동코드\t법정동명\t폐지여부",
                "2800000000\t인천광역시\t존재",
                "2811000000\t인천광역시 중구\t존재",
                "2811010100\t인천광역시 중구 중앙동1가\t존재",
                "2871000000\t인천광역시 강화군\t존재",
                "2872000000\t인천광역시 옹진군\t폐지",
                "4100000000\t경기도\t존재",
                "4111000000\t경기도 수원시\t존재",
                "4111100000\t경기도 수원시 장안구\t존재",
                "4111300000\t경기도 수원시 권선구\t존재",
                "4111010100\t경기도 수원시 팔달로1가\t존재",
                "4182000000\t경기도 가평군\t존재",
            ]
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("법정동코드 전체자료.txt", text.encode("cp949"))

        parsed = parse_mois_legal_district_zip(buffer.getvalue(), sido_codes={"28", "41"})

        self.assertEqual(
            parsed,
            {
                "28": {"28110": "인천광역시 중구", "28710": "인천광역시 강화군"},
                "41": {
                    "41111": "경기도 수원시 장안구",
                    "41113": "경기도 수원시 권선구",
                    "41820": "경기도 가평군",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
