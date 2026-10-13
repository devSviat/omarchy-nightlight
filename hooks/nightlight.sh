#!/bin/bash
# Rebuild the sunset-tracked night light schedule when the desktop starts, so
# the ramp is right for today even if the machine was off overnight.
exec "@CLI@" apply
