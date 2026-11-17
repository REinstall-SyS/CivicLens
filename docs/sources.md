# Hattiesburg source contract

Source review date: November 17, 2026.

The official [City Council page](https://www.hattiesburgms.com/council/) publishes meeting guidance and a historical archive link. The [council agenda page](https://www.hattiesburgms.com/council/agenda/) had no extractable agenda listing in the initial read. The city [public notice page](https://www.hattiesburgms.com/public-notice-signs/) links to a CivicClerk portal. At verification time, the browser retrieval service received HTTP 403 for the portal's front page. The tenant's official open OData feed and published PDF stream endpoints responded successfully to unauthenticated requests from the local CLI.

## CivicClerk

- Endpoint is `https://hattiesburgms.api.civicclerk.com/v1/Events`. Discovery pages records using an inclusive start date and exclusive end date.
- Published files expose `fileId`, `type`, `name`, `url`, and sometimes `publishOn`. The adapter uses the PDF file stream endpoint and preserves the official publication value.
- The date and time on two authentic agendas matched the wall time in the tenant's `startDateTime` field despite its `Z` suffix. The adapter interprets that field as Hattiesburg wall time and persists UTC. The PDF itself remains the primary reference.
- A new agenda or minutes file ID for the same event advances the document revision. Packets and other linked PDFs have separate file identities. Attachments within the configured archive limit are stored as PDFs. Larger attachments retain their official URLs and appear as link-only records.
- Only explicit approval or signature wording on the published minutes marks the document as authoritative for automated disposition. Unfamiliar layouts, draft minutes, and unclear motions can be reviewed by a human. A signed minutes PDF may start with a copied agenda; proceedings evidence starts after the publisher's divider.
- Discovery currently walks City Council and the other published event categories. Extraction primarily covers numbered Council headings with fiscal-year item IDs. Planning Commission and Board of Adjustment event and document metadata can appear even when the item layout is unsupported.

## Legistar

The [public calendar](https://hattiesburgms.legistar.com/Calendar.aspx) listed historic year choices and returned zero rows in its default current view. Requests to both tested Legistar Web API client paths returned HTTP 500. The bootstrap uses the known public historical meeting detail and its final agenda and minutes. This historical path is a curated adapter entry.

## Demonstration inventory

| Official meeting | Agenda | Minutes |
| --- | --- | --- |
| Jan. 8, 2019, City Council regular meeting | [Agenda PDF](https://hattiesburgms.legistar.com/View.ashx?GUID=79BB73AB-68B9-4536-8377-CC04C4B0E56B&ID=669983&M=A) | [Final minutes PDF](https://hattiesburgms.legistar.com/View.ashx?GUID=79BB73AB-68B9-4536-8377-CC04C4B0E56B&ID=669983&M=M) |
| Sept. 8, 2026, City Council | [Agenda PDF](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4556,plainText=false)) | [Approved and signed minutes PDF](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4623,plainText=false)) |
| Sept. 15, 2026, special called meeting | [Agenda PDF](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4565,plainText=false)) | [Approved and signed minutes PDF](https://hattiesburgms.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=4624,plainText=false)) |
