# Reference evaluation

The reference sample contains 17 manually checked agenda items and six search examples from two City Council meetings outside the demo set. Four official PDFs were read. Labels include agenda page, amounts, item-level disposition, vote, and disposition page where applicable. This bounded sample is a regression benchmark. It does not estimate performance across all Hattiesburg meeting types.

- July 21, 2026. [Agenda](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4494,plainText=false)) · [Minutes](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4527,plainText=false))
- August 4, 2026. [Agenda](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4518,plainText=false)) · [Minutes](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4583,plainText=false))

Run `python -m evaluation.run` from the repository root. Use `--pdf-folder .data` for an offline run using official PDF files named by file ID. Use `--output evaluation/results.json` to refresh the machine-readable report. The script creates a temporary database so benchmark records stay out of the demo.

| Metric | Observed |
| --- | ---: |
| Agenda item recall | 17/17 |
| Financial extraction precision | 9/9 |
| Financial extraction recall | 9/10 |
| Verified disposition precision | 5/5 |
| Verified disposition recall | 5/14 |
| Incorrect confirmed dispositions in the sample | 0 |
| Recorded vote match among verified decisions | 5/5 |
| Correct agenda and disposition PDF pages | 22/22 |
| Exact text-offset checks | 44/44 |
| Target record ranked first in SQLite keyword search | 6/6 |
| Documents processed | 4/4 |
| External model cost | $0 |

Examples of misses include OCR text corruption in the motion or headings, adjacent motions without a reliable item boundary, and an agenda/minutes identifier discrepancy for the airport master plan grant. The rules held those outcomes for review. Consult [results.json](results.json) for measured per-document time and every labeled disposition mismatch. Processing time excludes source downloads and Prefect startup. Search in this run used the SQLite fallback. The benchmark did not measure configured-model extraction or semantic retrieval relevance.
