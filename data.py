#!/home/matthias/tools/anaconda3/bin/python3

import numpy
import json
import pandas
from collections import defaultdict

class Settings:

  def __init__(self, data):
    self._year = data['year']
    self._organizers = tuple(data['organizers'])
    self._dates = data['dates']

  @property
  def year(self):
    return self._year

  @property
  def organizers(self):
    return self._organizers

  @property
  def dates(self):
    return self._dates.keys()

  @property
  def dates_sizes(self):
    return self._dates.items()

def parse_settings(config_data):
  return Settings(config_data['settings'])



def parse_penalties(config_data):
  return config_data['penalties']




class Person:

  def __init__(self, name, json_data):
    self._name = name
    self._firstname = json_data['firstname']
    self._lastname = json_data['lastname']
    self._chair = json_data['chair']
    self._group = json_data['group']
    self._role = json_data['role']
    self._history = defaultdict(set)

  @property
  def name(self):
    return self._name

  @property
  def firstname(self):
    return self._firstname

  @property
  def lastname(self):
    return self._lastname

  @property
  def chair(self):
    return self._chair

  @property
  def group(self):
    return self._group

  @property
  def role(self):
    return self._role

  def add_to_history(self, relative_year, other):
    self._history[relative_year].add(other)

  def get_history(self):
    return self._history

  def __str__(self):
    return self.name

  def __repr__(self):
    history = ", ".join( [ f'{year}: {others}' for year,others in self._history.items() ] )
      
    return f'{self.name} ({self.firstname} {self.lastname} is {self.role} in {self.chair}/{self.group}): {history}'

def parse_people(config_data):
  from itertools import permutations

  people = {}
  current_year = int(config_data['settings']['year'])
  for name,data in config_data['people'].items():
    people[name] = Person(name, data)
  for year,data in config_data['history'].items():
    year = int(year)
    for match in data:
      for pair in permutations(match, 2):
        people[pair[0]].add_to_history(current_year - year, pair[1])
  return people

def parse_registrations(file_name):
  sheet = pandas.read_csv(file_name, sep=';')
  dates = { column: set() for column in sheet.columns if column != 'name' }
  for idx,row in sheet.iterrows():
    for date in dates:
      if int(row[date]) == 1 and not isinstance(row['name'], float):
        dates[date].add(row['name'])
  return dates


if __name__ == '__main__':
  import sys

  config_file_name = sys.argv[1]

  config_data = json.loads(open(config_file_name, 'r').read())
  settings = parse_settings(config_data)
  penalties = parse_penalties(config_data)
  people = parse_people(config_data)

  for p,data in people.items():
    print(repr(data))

  dates = parse_registrations('registrations.csv')

  for date,date_people in dates.items():
    for p in date_people:
      if p not in people:
        sys.stderr.write(f'{p} is unknown!\n')

