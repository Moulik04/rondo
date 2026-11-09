# Data contract

The shared tables under `data/parquet/` that both tracks read. This file is written before the tables are built, and each table's pyarrow schema in `src/rondo/core/schemas.py` must match it (a test checks the column names). Tracks treat these files as read-only and find them through `RONDO_DATA_DIR`.

## Conventions

- **Format.** Parquet with zstd compression. Large tables are Hive-partitioned as `<table>/competition_id=<c>/season_id=<s>/part-0.parquet`, written match by match as row groups. Small tables are a single `<table>.parquet`.
- **Ids.** StatsBomb's own ids: `match_id`, `team_id`, `player_id` and `event_id` (the event UUID string). Rondo's cross-provider `person_id` arrives in Phase 3 (`player_xref`).
- **Source.** Every table built from StatsBomb comes from the commit pinned in `data/raw/statsbomb/SOURCE.json`.
- **Time.**
  - `period`: 1 and 2 are the halves, 3 and 4 extra time, 5 the penalty shootout.
  - `timestamp_s`: seconds since the start of the period (from StatsBomb's `timestamp`).
  - `minute` and `second`: StatsBomb's match clock; the second half starts at 45:00, extra time at 90:00 and 105:00.
- **Event coordinates (`x`, `y`, `end_x`, `end_y`).** StatsBomb's 120 × 80 pitch. The origin (0, 0) is the top-left corner, x runs along the pitch toward the opposition goal, and y runs down across it. Each event is drawn from the **acting team's** perspective, attacking left to right. Freeze frames and 360 frames use the same frame as their event.
- **SPADL coordinates.** 105 × 68 metres, origin bottom-left. Every action is turned so its team attacks left to right (socceraction's `play_left_to_right`).
- **Booleans.** StatsBomb omits flags that are false; Rondo stores them as `false`, never null.
- **Missing values** are null, and the column notes say when they occur.

## Tables

### competitions

**Grain:** one row per competition-season in scope. **Key:** (`competition_id`, `season_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| competition_id, season_id | int32 | |
| competition_name, season_name, country_name | string | |
| competition_gender | string | always `male` in scope |
| competition_youth, competition_international | bool | |
| scope | string | `core` or `extra` |
| scope_group | string | e.g. `full season`, `one team: Barcelona`, `tournament` |

### matches

**Grain:** one row per match. **Key:** `match_id`. Not partitioned.

| Column | Type | Notes |
|---|---|---|
| match_id | int32 | |
| competition_id, season_id | int32 | |
| scope | string | `core` or `extra` |
| match_date | date | |
| kick_off | string | local `HH:MM:SS.fff` as given; can be null |
| home_team_id, away_team_id | int32 | |
| home_score, away_score | int16 | final score as given, excluding any shootout |
| match_week | int16 | |
| competition_stage | string | |
| stadium_id, referee_id | int32 | nullable |
| stadium_name, referee_name | string | nullable |
| match_status, match_status_360 | string | |
| data_version, shot_fidelity_version, xy_fidelity_version | string | from `metadata`; needed by socceraction |
| has_360 | bool | `match_status_360 == "available"` |

### match_periods

**Grain:** one row per period played in a match. **Key:** (`match_id`, `period`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| match_id | int32 | |
| period | int16 | 1–5 |
| length_s | float64 | the latest `Half End` event's `timestamp_s` in that period |

### teams

**Grain:** one row per team. **Key:** `team_id`. Built from matches.

| Column | Type | Notes |
|---|---|---|
| team_id | int32 | |
| team_name | string | |
| team_gender | string | |
| country_name | string | nullable |

### players

**Grain:** one row per StatsBomb player. **Key:** `player_id`. Built from lineups. Where a player's name or nickname differs between lineups, the most recent match's version is kept, and `n_name_variants` counts the distinct names seen.

| Column | Type | Notes |
|---|---|---|
| player_id | int32 | |
| player_name | string | full name |
| player_nickname | string | nullable; the name commonly used |
| country_name | string | nullable |
| n_matches_listed | int32 | lineups the player appears in |
| n_name_variants | int16 | |

### lineups

**Grain:** one row per player listed for a team in a match (starters, substitutes who came on, and unused substitutes). **Key:** (`match_id`, `player_id`).

| Column | Type | Notes |
|---|---|---|
| match_id, team_id, player_id | int32 | |
| jersey_number | int16 | |
| started | bool | has a position spell with `start_reason == "Starting XI"` |
| n_cards | int16 | |
| red_card_minute | float32 | match-clock minute of a red or second-yellow card; null if none |
| cards | string | JSON list as given |

Also **lineup_positions**: **grain** one row per position spell (position, from, to) per player per match. **Key:** (`match_id`, `player_id`, `spell`).

| Column | Type | Notes |
|---|---|---|
| match_id, team_id, player_id | int32 | |
| spell | int16 | 0-based order |
| position_id | int16 | StatsBomb position id |
| position_name | string | |
| position_group | string | GK, CB, FB/WB, DM/CM, AM, W, ST (mapping below) |
| from_clock_s, to_clock_s | float32 | match-clock seconds; `to` is null for "until the end". Stored as given. Not used for minutes: some matches' spells are inconsistent |
| from_period, to_period | int16 | `to_period` null as above |
| start_reason, end_reason | string | |

### events

**Grain:** one row per StatsBomb event. **Key:** `event_id`. Partitioned by competition and season.

| Column | Type | Notes |
|---|---|---|
| event_id | string | UUID |
| match_id | int32 | |
| index | int32 | order within the match |
| period | int16 | |
| timestamp_s | float64 | seconds since period start |
| minute, second | int16 | match clock |
| type_id | int16 | |
| type_name | string | e.g. `Pass`, `Shot`, `Ball Receipt*` |
| possession | int32 | possession sequence number within the match |
| possession_team_id | int32 | |
| play_pattern | string | |
| team_id | int32 | |
| player_id, position_id | int32, int16 | null for team events such as `Half Start` |
| position_name | string | nullable |
| x, y | float32 | event location; null where none is given |
| duration | float32 | seconds; nullable |
| under_pressure, off_camera, out, counterpress | bool | |
| related_events | list\<string\> | event ids |
| details | string | JSON object holding every remaining key (the type-specific object such as `pass` or `shot`, `tactics`, and so on), so nothing is lost |

### shots

**Grain:** one row per Shot event. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id, team_id, player_id | int32 | |
| period, minute, second | int16 | |
| timestamp_s | float64 | |
| x, y | float32 | shot location |
| end_x, end_y, end_z | float32 | `end_z` is height in the same units; nullable |
| statsbomb_xg | float32 | StatsBomb's own model. Internal use only: never published (see `DATA_TERMS.md`) |
| shot_type | string | `Open Play`, `Penalty`, `Free Kick`, `Corner`, `Kick Off` |
| outcome | string | `Goal`, `Saved`, `Off T`, `Blocked`, `Wayward`, `Post`, `Saved Off Target`, `Saved to Post` |
| is_goal, is_penalty | bool | |
| body_part, technique | string | |
| first_time, one_on_one, open_goal, aerial_won, deflected, follows_dribble, under_pressure | bool | |
| key_pass_id | string | nullable |
| has_freeze_frame | bool | |
| play_pattern | string | |

### shot_freeze_frames

**Grain:** one row per player in a shot's freeze frame. **Key:** (`event_id`, `player_id`). Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | the shot |
| match_id | int32 | |
| player_id | int32 | |
| position_name | string | |
| teammate | bool | teammate of the shooter |
| x, y | float32 | |

### passes

**Grain:** one row per Pass event. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id, team_id, player_id | int32 | |
| period | int16 | |
| timestamp_s | float64 | |
| x, y, end_x, end_y | float32 | |
| length, angle | float32 | length in pitch units; angle in radians |
| height | string | `Ground Pass`, `Low Pass`, `High Pass` |
| recipient_id | int32 | nullable |
| outcome | string | null means completed; otherwise `Incomplete`, `Out`, `Pass Offside`, `Unknown`, `Injury Clearance` |
| is_complete | bool | `outcome` is null |
| pass_type | string | nullable: `Corner`, `Free Kick`, `Goal Kick`, `Throw-in`, `Kick Off`, `Recovery`, `Interception` |
| body_part, technique | string | nullable |
| cross, switch, cut_back, through_ball, shot_assist, goal_assist, aerial_won, deflected, miscommunication, under_pressure | bool | |
| assisted_shot_id | string | nullable |
| play_pattern | string | |

### carries

**Grain:** one row per Carry event. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id, team_id, player_id | int32 | |
| period | int16 | |
| timestamp_s | float64 | |
| x, y, end_x, end_y | float32 | |
| duration | float32 | |
| under_pressure | bool | |

### pressures

**Grain:** one row per Pressure event. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id, team_id, player_id | int32 | |
| period | int16 | |
| timestamp_s | float64 | |
| x, y | float32 | |
| duration | float32 | |
| counterpress | bool | |

### defensive_actions

**Grain:** one row per defensive event, meaning a `Duel`, `Interception`, `Block`, `Clearance`, `Ball Recovery`, `50/50`, `Foul Committed` or `Shield` event. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id, team_id, player_id | int32 | |
| period | int16 | |
| timestamp_s | float64 | |
| x, y | float32 | |
| action | string | the event type above |
| subtype | string | nullable: duel type (`Tackle`, `Aerial Lost`), foul type |
| outcome | string | nullable, as given |
| is_success | bool | nullable where StatsBomb gives no outcome (documented per action in `reports/data_quality.md`) |
| card | string | nullable, for fouls |
| counterpress, under_pressure | bool | |

### frames_360

**Grain:** one row per visible player per event that has a 360 frame. **Key:** (`event_id`, `slot`). Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id | int32 | |
| slot | int16 | order within the frame (360 frames carry no player ids) |
| teammate, actor, keeper | bool | `teammate` is relative to the event's actor |
| x, y | float32 | |

**Known gap:** in 7 matches at the pinned commit (Leverkusen 2023/24, Inter Miami 2023, Paris Saint-Germain 2022/23), none of the 360 frames' event ids appear in the match's events file. The 360 files were added on 26 May 2026; the events files date from 14 December 2023. Those frames are stored, but they don't join to `events`. The list is in `reports/data_quality.md`.

### visible_areas_360

**Grain:** one row per event that has a 360 frame. **Key:** `event_id`. Partitioned.

| Column | Type | Notes |
|---|---|---|
| event_id | string | |
| match_id | int32 | |
| polygon | list\<float32\> | x1, y1, x2, y2, … as given |
| n_points | int16 | |
| is_valid | bool | shapely `Polygon.is_valid` |
| area | float32 | pitch units² |
| n_visible_players | int16 | |

### player_match_minutes

**Grain:** one row per player who took the pitch in a match. **Key:** (`match_id`, `player_id`). Not partitioned.

**Built from the event stream**, not from `lineup_positions`. In some matches those spells run backwards in time or overlap (counted in `reports/data_quality.md`).
- **On:** kick-off for players in the `Starting XI` event, otherwise the `Substitution` event that brought them on.
- **Off:** the `Substitution` that took them off, or a red or second-yellow card (`Foul Committed` or `Bad Behaviour`), otherwise the end of the last period played.

| Column | Type | Notes |
|---|---|---|
| match_id, team_id, player_id | int32 | |
| competition_id, season_id | int32 | |
| started | bool | |
| minutes | float32 | elapsed playing time, excluding the shootout, ending at a red card |
| minute_on, minute_off | float32 | elapsed minutes since kick-off |
| sent_off | bool | |
| primary_position_group | string | the group of most of the player's events |
| minutes_by_group | string | JSON object: group to minutes, splitting minutes by the share of the player's events at each position |

**Event time to elapsed time:** the length of all earlier periods plus the event's `timestamp_s`. Period lengths come from each period's last `Half End` event, and a match's length is the sum of periods 1–4.

### spadl_actions

**Grain:** one row per SPADL action. **Key:** (`provider`, `match_id`, `action_id`). Partitioned by provider, competition and season: `spadl_actions/provider=statsbomb/competition_id=…/season_id=…/`.

| Column | Type | Notes |
|---|---|---|
| provider | string | `statsbomb` (Phase 2 adds `wyscout`) |
| match_id | int32 | socceraction's `game_id` |
| action_id | int32 | order within the match |
| original_event_id | string | the provider's event id; null for the dribbles socceraction inserts between actions |
| period_id | int16 | |
| time_seconds | float64 | since period start |
| team_id, player_id | int32 | |
| start_x, start_y, end_x, end_y | float32 | metres, each team attacking left to right |
| type_id, result_id, bodypart_id | int16 | |
| type_name, result_name, bodypart_name | string | |

**What socceraction 1.5.3's StatsBomb converter does,** checked match by match by `spadl_reconciles_passes_shots_carries` and `spadl_actions_trace_to_events`:
- **Pass:** one pass-family action (`pass`, `cross`, `throw_in`, `freekick_crossed`, `freekick_short`, `corner_crossed`, `corner_short`, `goalkick`).
  - Passes with outcome `Injury Clearance` or `Unknown` are dropped as not part of play.
  - A pass of type `Interception` also yields an `interception` action just before it.
- **Shot:** one `shot`, `shot_freekick` or `shot_penalty`, including shootout kicks (period 5).
- **Carry:** one `dribble`.
- **Inserted dribbles:** socceraction also inserts `dribble` actions between consecutive actions where the ball moved. These have a null `original_event_id`.
- **No SPADL action:** many event types have none, e.g. `Pressure`, `Ball Receipt*` and `Ball Recovery`. Counts by type are in `reports/data_quality.md`.

## Position groups

StatsBomb's 25 positions map to seven groups:

| StatsBomb positions (id) | Group |
|---|---|
| Goalkeeper (1) | GK |
| Right Center Back (3), Center Back (4), Left Center Back (5) | CB |
| Right Back (2), Left Back (6), Right Wing Back (7), Left Wing Back (8) | FB/WB |
| Right Defensive Midfield (9), Center Defensive Midfield (10), Left Defensive Midfield (11), Right Center Midfield (13), Center Midfield (14), Left Center Midfield (15) | DM/CM |
| Right Attacking Midfield (18), Center Attacking Midfield (19), Left Attacking Midfield (20) | AM |
| Right Midfield (12), Left Midfield (16), Right Wing (17), Left Wing (21) | W |
| Right Center Forward (22), Striker (23), Left Center Forward (24), Secondary Striker (25) | ST |

Two judgement calls:
- **Right and Left Midfield go to W.** In StatsBomb's lineups these are the wide players of a four-man midfield.
- **Secondary Striker goes to ST.** It's a forward role, not an attacking midfielder.

---

## Phase 2: Wyscout open data (raw tables, prefixed `wy_`)

Source: figshare collection 10.6084/m9.figshare.c.4415000.v5, recorded with checksums in `data/raw/wyscout/SOURCE.json`.
- **Names:** 899 player names and 8 team names in the raw files carry literal `\uXXXX` escapes. Rondo decodes them and removes soft hyphens (U+00AD).
- **Coordinates** (`x`, `y`, `end_x`, `end_y`): Wyscout's 0–100 scale as given, as percentages of the pitch's length and width. y runs from the top, and each team attacks left to right.
- **Wyscout SPADL:** `spadl_actions` with `provider = 'wyscout'`, converted by socceraction 1.5.3. A SPADL action starts at (x × 1.05, (100 − y) × 0.68), except that socceraction places goal kicks at (5, 34) and moves keeper saves to the keeper's goal. `original_event_id` is the Wyscout event id as text, or null for inserted dribbles.

### wy_competitions

**Grain:** one row per competition. **Key:** `competition_id`. Not partitioned.

| Column | Type | Notes |
|---|---|---|
| competition_id | int32 | Wyscout id |
| name, area_name, format, type | string | |

### wy_matches

**Grain:** one row per match. **Key:** `match_id`. Not partitioned.

| Column | Type | Notes |
|---|---|---|
| match_id, competition_id, season_id, round_id | int32 | |
| gameweek | int16 | |
| date_utc | timestamp | kick-off, UTC |
| label, status, duration, venue | string | |
| home_team_id, away_team_id | int32 | |
| home_score, away_score | int16 | score after 90 minutes |
| home_score_ht, away_score_ht | int16 | half-time |
| home_score_et, away_score_et | int16 | cumulative after extra time; 0 if none was played |
| home_score_p, away_score_p | int16 | penalty shootout |
| home_goals, away_goals | int16 | goals before any shootout: the larger of the score and the extra-time score |

### wy_teams

**Grain:** one row per team. **Key:** `team_id`. Not partitioned.

| Column | Type | Notes |
|---|---|---|
| team_id | int32 | |
| name, official_name, city, area_name, type | string | names decoded |

### wy_players

**Grain:** one row per player in Wyscout's players file. **Key:** `player_id`. Not partitioned.

| Column | Type | Notes |
|---|---|---|
| player_id | int32 | |
| short_name, first_name, middle_name, last_name | string | decoded |
| birth_date | date | **internal only** (minors rule); never published |
| role | string | GK, DF, MD, FW |
| foot | string | |
| height, weight | int16 | cm, kg as given |
| birth_area, passport_area | string | |
| current_team_id, current_national_team_id | int32 | nullable (the raw file sometimes holds the string "null") |

### wy_lineups

**Grain:** one row per player listed in a match (lineup or bench). **Key:** (`match_id`, `player_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| match_id, team_id, player_id | int32 | |
| status | string | `lineup` or `bench` |
| goals, own_goals, assists, yellow_cards, red_cards | int16 | as given on the match sheet |
| sub_in_minute, sub_out_minute | int16 | null if not substituted. Six team-matches store substitutions as the string "null"; they have none here. |

### wy_events

**Grain:** one row per Wyscout event. **Key:** `event_id`. Partitioned by competition and season.

| Column | Type | Notes |
|---|---|---|
| event_id | int64 | |
| match_id | int32 | |
| period | int16 | 1, 2, 3 and 4 (extra time), 5 (shootout) |
| match_period | string | Wyscout's `1H`, `2H`, `E1`, `E2`, `P` |
| event_sec | float64 | seconds since the period start |
| type_id, subtype_id | int16 | |
| type_name, subtype_name | string | e.g. `Free Kick` / `Corner` |
| team_id, player_id | int32 | `player_id` null where Wyscout gives 0 |
| x, y, end_x, end_y | float32 | 0–100, as given |
| tags | list\<int32\> | Wyscout tag ids (e.g. 101 goal, 102 own goal, 1801 accurate) |

## Phase 2: cross-provider links

### match_xref

**Grain:** one row per match linked across providers (so far: the 64 matches of the 2018 World Cup, StatsBomb and Wyscout). **Key:** `sb_match_id` (and `wy_match_id`, also unique). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| competition | string | |
| sb_match_id, wy_match_id | int32 | |
| sb_date | date | StatsBomb's local match date |
| wy_date_utc | timestamp | |
| date_diff_days | int16 | |
| sb_home_team_id, sb_away_team_id | int32 | |
| wy_team_for_sb_home, wy_team_for_sb_away | int32 | the Wyscout team on each StatsBomb side |
| sides_agree | bool | both providers name the same team as home |
| score_agrees | bool | |
| names_matched | int16 | team names that agree exactly (0–2) |
| method | string | the evidence used |
| confidence | string | `high` (both names match, same date) or `medium` |

### team_xref

**Grain:** one row per StatsBomb–Wyscout team pair seen in linked matches. **Key:** (`sb_team_id`, `wy_team_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| sb_team_id, wy_team_id | int32 | |
| sb_name, wy_name | string | |
| n_matches | int16 | linked matches with this pair |
| by_name, by_elimination | int16 | how the pair was aligned in those matches |

## Phase 2: tracking

### tracking_frames

**Grain:** one row per object (each player, and the ball) per frame. **Key:** (`provider`, `match_id`, `period`, `frame`, `object_id`). Partitioned by provider and match: `tracking_frames/provider=…/match_id=…/`.

| Column | Type | Notes |
|---|---|---|
| provider | string | `dfl` (Gradient later) |
| match_id | string | provider's id, e.g. `J03WMX` (DFL-MAT-J03WMX) |
| period | int16 | |
| frame | int32 | provider frame number. DFL restarts per period (10,000 in the first half, 100,000 in the second). |
| time_s | float64 | seconds since the period start |
| object_id | string | provider person id (e.g. `DFL-OBJ-…`), or `ball` |
| team_id | string | null for the ball |
| jersey_no | int16 | |
| x, y | float32 | **metres, origin at the centre spot**, x along the length (−52.5 to 52.5 on a 105 m pitch), y across it from bottom to top. Positions are absolute: teams swap ends at half-time (see `tracking_meta.home_attacks`). |
| z | float32 | ball height in metres; null for players |
| provider_speed | float32 | DFL's own speed value as given (units unverified; Rondo computes speeds from positions) |

**Speeds.** Rondo computes speed from positions over 5 frames (0.2 s). Any measurement above 12 m/s is a tracking glitch (check `tracking_speed_cap`): physical metrics exclude it and report how many were excluded. The positions themselves are kept as given.
| ball_alive | bool | the ball is in play |
| ball_owning_team_id | string | nullable |

DFL frames were loaded with kloppy 3.19's Sportec loader in its `sportec` coordinate system.

### tracking_meta

**Grain:** one row per match and period. **Key:** (`provider`, `match_id`, `period`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| provider, match_id, competition | string | |
| match_date | date | |
| home_team_id, home_team_name, away_team_id, away_team_name | string | |
| pitch_length, pitch_width | float32 | metres |
| frame_rate | float32 | Hz |
| period | int16 | |
| first_frame, last_frame, n_frames | int32 | |
| start_s, end_s | float64 | seconds |
| home_attacks | string | `left` or `right`: which way the home team attacks in this period |

### dfl_events

**Grain:** one row per `<Event>` element in DFL's raw event XML. **Key:** (`match_id`, `event_id`). Not partitioned. Read with lxml rather than kloppy, which synthesises some events and loses others' types.

| Column | Type | Notes |
|---|---|---|
| match_id, event_id | string | |
| event_time | string | ISO time as given |
| event_type | string | DFL type (the child element), e.g. `Play`, `ShotAtGoal`, `Caution`, `Delete` |
| event_subtype | string | nullable (the grandchild element, e.g. `Pass`) |
| team_id, player_id | string | nullable |
| x, y | float32 | as given by the event feed (metres, origin at a corner; not the tracking frame) |
| attributes | string | JSON of the event's attributes |

### dfl_lineups

**Grain:** one row per player on a DFL match sheet. **Key:** (`match_id`, `player_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| match_id, team_id, team_name, player_id | string | |
| first_name, last_name | string | |
| jersey_no | int16 | |
| starting | bool | |
| starting_position | string | kloppy's position name |

---

## Phase 3: identity and the minors rule

These tables hold birth dates and identity evidence. They live under `data/parquet/` like the rest and are **never published**; anything published goes through `core.public.display_ok`.

### team_wikidata

**Grain:** one row per provider team. **Key:** (`provider`, `team_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| provider | string | `statsbomb`, `wyscout`, `dfl` |
| team_id | string | provider id, as text |
| team_name | string | |
| kind | string | `club` or `national` |
| qid | string | Wikidata item, e.g. `Q7156` |
| qid_label, qid_description | string | as Wikidata gives them |
| search_text | string | the search that found it |
| rank | int16 | position among the search results |
| candidates | string | the first five results, for review |

### player_xref

**Grain:** one row per provider player: StatsBomb players who played, Wyscout lineup players, DFL match-sheet players. **Key:** (`provider`, `provider_player_id`). Not partitioned.

| Column | Type | Notes |
|---|---|---|
| person_id | string | Rondo's id for the person: `wd:<QID>` when linked to Wikidata with high or medium confidence, else `<provider>:<id>` of one of their provider ids. Low-confidence links are never merged into a person. |
| provider, provider_player_id | string | |
| name | string | the provider's display name |
| qid | string | Wikidata item, or null |
| status | string | `linked`, `ambiguous`, `weak name match`, `unmatched` |
| method | string | the evidence behind the link |
| confidence | string | `high`, `medium`, `low` (low: name search alone; never used to verify an age) |
| name_score | float32 | 0–1 |
| team_support | int16 | how many of the player's teams list them as a member around those dates |
| dob_agrees | bool | the Wyscout birth date equals Wikidata's (null if not compared) |
| n_candidates | int16 | |
| same_match_partner | string | the other provider's id from the 2018 World Cup same-match pairing |

### wikidata_people

**Grain:** one row per Wikidata person linked to a provider player. **Key:** `qid`. Not partitioned. Internal only.

| Column | Type | Notes |
|---|---|---|
| qid | string | |
| label | string | shortest name in the eight languages fetched |
| birth_date | date | |
| birth_date_precision | int16 | Wikidata precision: 11 day, 10 month, 9 year |
| names | string | JSON list of labels and aliases |

### player_age_status

**Grain:** one row per person per competition-season they appear in. **Key:** (`person_id`, `competition_season`). Not partitioned. Internal only.

| Column | Type | Notes |
|---|---|---|
| person_id | string | |
| competition_season | string | `statsbomb:<competition>/<season>`, `wyscout:<competition>/<season>`, `dfl:<DFL-COM-id>/2022-23` |
| provider | string | |
| competition_id, season_id | int32 | null for DFL |
| window_start, window_end | date | that competition-season's first and last match in the data |
| status | string | `verified_adult`, `minor_during_season`, `unverified` |
| birth_date_low, birth_date_high | date | the range of possible birth dates (equal when exact) |
| birth_date_source | string | `wikidata`, `wyscout` or `wikidata+wyscout` |
| note | string | `no birth date`, `sources disagree`, or null |
