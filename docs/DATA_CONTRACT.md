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
