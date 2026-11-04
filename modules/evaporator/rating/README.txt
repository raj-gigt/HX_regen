FOUR EVAPORATOR RATING APPLICATIONS
===================================

Files:
- k_type_reboiler_rating.py
- falling_film_rating.py
- horizontal_thermosyphon_rating.py
- vertical_thermosyphon_rating.py

Installation:
  pip install -r requirements.txt

Run one application at a time, for example:
  streamlit run k_type_reboiler_rating.py

The other applications are launched using their respective filenames.

The Kern segmented-baffle j_h chart supplied by the user is included. The
rating applications contain their own approximate digitized lookup values.
See KERN_JH_CHART_DIGITISATION.md and PRESSURE_DROP_IMPLEMENTATION.md for
source and applicability limitations.

These are the four rating scripts only; they do not include or alter the
four sizing scripts.
