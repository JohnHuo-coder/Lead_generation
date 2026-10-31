---
name: meetings
description: Use when researching meeting rooms, event space, seated capacity, number of rooms, layout, or meeting room vs banquet hall.
---

## researcher
- Judge only the meeting-space condition. Guest-restaurant menus and
  ordinary F&B are not evidence. Named venues on an official events,
  meetings, or private-event / room-rental page with seated or standing
  capacity are in-scope event rooms, including a restaurant or bar buyout
  listed there.
- Capacity tables and named rooms can establish the matching part of the
  condition. Do not wait for particular wording.
- Guest lounges, coworking, community areas, and 24-hour productivity
  spaces are not meeting or event rooms unless the official meetings page
  lists them as bookable event space.
- Guest-house rules (parties/events not allowed, pets, smoking) neither
  prove nor refute meeting space. Guest-room occupancy is not capacity.
- Prefer the official meetings/events/facilities/faqs page over Cvent or
  other directories when they disagree on room count, named rooms, or
  capacity. Do not keep searching the same directory to reconcile that
  disagreement.
- Prefer a named-room layout or area table over a directory total or
  "1 room holding N" figure. Aggregate seating across rooms is not a
  single-room capacity. Do not treat that mismatch as equal-rank conflict.
- If the official page already lists meeting-room count and seated
  capacity, judge from that inventory. If every in-scope listed value
  fails the required threshold, layout, or room type, that can establish
  negative_when. Do not keep searching other layouts unless the
  requirement asks for them.
- If the only listed in-scope room is below the threshold in standing,
  reception, or "up to N", that can establish negative_when. Do not wait
  for a seated layout number.
- Official FAQ "no meeting room on site" can establish negative_when.
  Directory "No Information Available" cannot.
- Cvent related-venue or "similar venues" sizes are not this property.

## query
- First query: open keywords for meeting or event space and capacity.
  Do not use site:. Keep soi, street number, and neighborhood tokens.
  Drop only parent-company ("by …") and extra marketing descriptors.
- If that returns nothing on-target, try Cvent, then site: on the
  official domain (meetings, events, facilities, faqs, factsheets,
  room-rental). Keep the location tokens.
- If the official domain is already known and inventory is still
  missing, use site:{domain} faqs OR facilities OR meetings. Do not
  search gallery, city event-calendar, or guest-room pages.
- After a successful open query, you may try Cvent as an open query, or
  site: on the official hotel domain if the open query missed the fact
  page.
- Use site:cvent.com only if an open Cvent query fails.

## selector
- Prefer official meeting/event/facilities/faqs/factsheet/room-rental
  pages, or the hotel group's event portal; then Cvent, Northstar,
  HotelPlanner, Travel Weekly, BTN, or Conference Hotel Group.
- If an official fact-page URL is a candidate, select it. Do not skip it
  for the homepage, an OTA guest-room page, or because the snippet looks
  thin.
- Skip sibling properties, different-city locations, and other businesses
  that only share a neighborhood or brand family.

## extract
- Extract named rooms, room types (meeting room, banquet hall, ballroom,
  private-event venue), layouts, and seated or standing capacities,
  including values below the required headcount. Do not omit a room
  because it seats fewer than the threshold.
- Extract how many rooms or whether spaces combine, when the source says so.
- Extract official statements that the property has no meeting room.
- A capacity table on a page about this property is in scope even if a
  row uses only the room name as subject.
- Do not extract guest-dining menus, guest-room occupancy, house rules,
  catering-only facts, directory "No Information Available", or similar-
  venue modules for this requirement.
