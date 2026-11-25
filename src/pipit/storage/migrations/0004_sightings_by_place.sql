-- Schema 4: sightings by place and date, for loading a recorded visit into Enter Sightings
-- (checked as the place, date and start time are typed) and a place's visits.
CREATE INDEX sightings_place_date ON sightings(location_xml_id, date);
