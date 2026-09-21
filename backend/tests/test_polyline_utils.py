"""Polyline -> PostGIS geometry conversion."""

from app.strava.polyline_utils import decode_polyline, to_linestring_ewkt, to_point_ewkt

A, B, C = (47.50, 19.00), (47.51, 19.01), (47.52, 19.02)


def _coords(ewkt: str | None) -> list[tuple[float, float]]:
    """Parse 'SRID=4326;LINESTRING(lng lat, ...)' back into [(lat, lng), ...]."""
    assert ewkt is not None
    inner = ewkt.split("LINESTRING(", 1)[1].rstrip(")")
    pairs = [p.strip().split() for p in inner.split(",")]
    return [(float(lat), float(lng)) for lng, lat in pairs]


class TestPointEwkt:
    def test_longitude_comes_first_in_wkt(self):
        # The classic way to get PostGIS wrong: WKT is (x y) = (lng lat).
        assert to_point_ewkt(47.4979, 19.0402) == "SRID=4326;POINT(19.0402 47.4979)"


class TestLineStringEwkt:
    def test_out_and_back_keeps_the_return_leg(self):
        """Regression: global dedup dropped every point after the turnaround."""
        assert _coords(to_linestring_ewkt([A, B, C, B, A])) == [A, B, C, B, A]

    def test_closed_loop_keeps_its_closing_point(self):
        """Regression: a loop ending where it began was truncated to an open line."""
        assert _coords(to_linestring_ewkt([A, B, C, A])) == [A, B, C, A]

    def test_lap_route_keeps_every_lap(self):
        two_laps = [A, B, C, A, B, C, A]
        assert _coords(to_linestring_ewkt(two_laps)) == two_laps

    def test_consecutive_duplicates_are_collapsed(self):
        """A paused GPS records the same fix twice running; that is noise."""
        assert _coords(to_linestring_ewkt([A, A, A, B, B, C])) == [A, B, C]

    def test_single_point_is_not_a_route(self):
        assert to_linestring_ewkt([A]) is None

    def test_standing_still_is_not_a_route(self):
        assert to_linestring_ewkt([A, A, A]) is None

    def test_empty_input_is_not_a_route(self):
        assert to_linestring_ewkt([]) is None


class TestDecodePolyline:
    def test_decodes_to_lat_lng_pairs(self):
        # Encoded form of the classic (38.5,-120.2), (40.7,-120.95), (43.252,-126.453)
        decoded = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        assert len(decoded) == 3
        assert decoded[0] == (38.5, -120.2)

    def test_missing_input_is_empty_not_an_error(self):
        assert decode_polyline(None) == []
        assert decode_polyline("") == []

    def test_corrupt_input_is_empty_not_an_error(self):
        """The decoder does not raise on garbage - it returns absurd coordinates."""
        assert decode_polyline("!!!not-a-polyline!!!") == []

    def test_out_of_range_coordinates_are_rejected_wholesale(self):
        """Regression: an impossible latitude would break the PostGIS insert mid-sync.

        Encodes (200.0, 500.0) followed by a perfectly valid Budapest point - the
        valid one is discarded too, because a corrupt encoding earns no trust.
        """
        assert decode_polyline("_ouce@_gwj~A~cxa\\~hxvzA") == []
