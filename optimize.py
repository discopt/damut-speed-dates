#!/home/matthias/tools/anaconda3/bin/python3

import sys
from data import *
import json
import itertools
import pyscipopt

def print_usage():
  sys.stderr.write(f'Usage: {sys.argv[0]} CONFIG-JSON REGISTRATIONS-CSV [RESULTS-JSON [PARTIAL-RESULTS-JSON]]\n')
  sys.stderr.flush()

if __name__ == '__main__':
  from math import ceil, floor

  if len(sys.argv) <= 2:
    print_usage()
    sys.exit(1)

  config_file_name = sys.argv[1]
  registrations_file_name = sys.argv[2]
  results_file_name = sys.argv[3] if len(sys.argv) > 3 else None
  partial_results_file_name = sys.argv[4] if len(sys.argv) > 4 else None

  config_data = json.loads(open(config_file_name, 'r').read())
  settings = parse_settings(config_data)
  penalties = parse_penalties(config_data)
  all_people = parse_people(config_data)

  dates = parse_registrations(registrations_file_name)

  # Check for unknown people.
  unknown_people = set()
  people = set()
  for date,date_people in dates.items():
    for p in date_people:
      if p not in all_people:
        unknown_people.add(p)
      people.add(p)
  for p in unknown_people:
    sys.stderr.write(f'{p} is unknown!\n')
  if unknown_people:
    sys.exit(1)

  # Construct possible matches for each date.
  matches = {}
  pairs = set()
  pairs_to_matches = {}
  for date,date_people in dates.items():
    print(f'Considering date <{date}>.')
    date_size = settings.sizes[date]
    date_people = dates[date]
    matches[date] = []
    for s in range(2, date_size+1):
      matches[date].extend( map(frozenset, itertools.combinations(date_people, s)) )
    print(f'  {len(date_people)} participants to form matches of size >= 2 and <= {date_size}, giving {len(matches[date])} different matches.')
    pairs_to_matches[date] = defaultdict(set)
    for match in matches[date]:
      for pair in itertools.combinations(match, 2):
        pair = frozenset(pair)
        pairs_to_matches[date][pair].add(match)
        pairs.add(pair)

  # Count roles for each date.
  count_roles = {}
  for date,date_people in dates.items():
    count_roles[date] = { r: 0 for r in ROLES }
    for p in date_people:
      p_data = all_people[p]
      count_roles[date][p_data.role] += 1

  # Create SCIP model.
  model = pyscipopt.Model()

  # indicator for each match on each date.
  var_match = {}
  for date in dates:
    for match in matches[date]:
      var_match[date, match] = model.addVar(name=f'match_{date}_{"#".join(match)}', vtype='B')

  # Load partial solution.
  if partial_results_file_name is not None:
    with open(partial_results_file_name, 'r') as fp:
      partial_results = json.loads(fp.read())
      assert 'solution' in partial_results
      for date,fixed_matches in partial_results['solution'].items():
        for match in fixed_matches:
          model.chgVarLb(var_match[date, frozenset(match)], 1)

  # indicator whether a certain pair of people meets.
  var_count_meet = {}
  for pair in pairs:
    p1,p2 = tuple(pair)
    var_count_meet[pair] = model.addVar(name=f'count_meet_{p1}_{p2}', vtype='B')

  # Counter how often someone meets someone of a certain role.
  var_count_role = {}
  var_too_many_role = {}
  var_too_few_role = {}
  for p in people:
    for r in ROLES:
      var_count_role[p,r] = model.addVar(name=f'count_role_{p}_{r}', vtype='I')
      var_too_many_role[p,r] = model.addVar(name=f'too_many_role_{p}_{r}', vtype='I')
      var_too_few_role[p,r] = model.addVar(name=f'too_few_role_{p}_{r}', vtype='I')

  # Counter for number of same group.
  var_count_same_group = {}
  for p in people:
    var_count_same_group[p] = model.addVar(name=f'count_same_group_{p}', vtype='I')

  # Counter for number of same chair.
  var_count_same_chair = {}
  for p in people:
    var_count_same_chair[p] = model.addVar(name=f'count_same_chair_{p}', vtype='I')

  # Counter for unassigned per date.
  var_unassigned = {}
  for date,date_people in dates.items():
    for o in settings.organizers:
      if o in date_people:
        var_unassigned[date,o] = model.addVar(name=f'is_unassigned_{date}_{o}', vtype='B')

  # Counter indicator for unassigned.
  var_num_unassigned = { i: {} for i in UNASSIGNED }
  for i in UNASSIGNED:
    for o in settings.organizers:
      var_num_unassigned[i][o] = model.addVar(name=f'is_num_unassigned_{i}_{o}', vtype='B')
  
  ### CONSTRAINTS ###

  # Count how often a certain pair of people meets.
  for pair in pairs:
    model.addCons( var_count_meet[pair] == sum( var_match[date, match] for date in dates for match in pairs_to_matches[date].get(pair, []) ), f'count_meet_{"#".join(pair)}')

  # Count how often someone meets a certain role.
  for p in people:
    for r in ROLES:
      model.addCons( var_count_role[p,r] == sum( sum(1 for p2 in match if p != p2 and all_people[p2].role == r) * var_match[date, match] for date in dates for match in matches[date] if p in match ), f'count_role_{p}_{r}')

      indicator_same_role = 1 if all_people[p].role == r else 0
      expected_count = 0.0
      for date in dates:
        old = expected_count
        expected_count += (settings.sizes[date]-1) * (count_roles[date][r] - indicator_same_role) / (len(dates[date]) - 1)
#      print(f'Expecting that {p} meets {expected_count} colleagues that are {r}.')

      model.addCons( var_too_many_role[p,r] >= var_count_role[p,r] - ceil(expected_count)  )
      model.addCons( var_too_few_role[p,r] >= floor(expected_count) - var_count_role[p,r] )

  # Count number of same group.
  for p in people:
    model.addCons( var_count_same_group[p] == sum( var_count_meet.get(frozenset((p, p2)), 0) for p2 in people if all_people[p].group == all_people[p2].group ), f'count_same_group_{p}')
  
  # Count number of same chair.
  for p in people:
    model.addCons( var_count_same_chair[p] == sum( var_count_meet.get(frozenset((p, p2)), 0) for p2 in people if all_people[p].chair == all_people[p2].chair ), f'count_same_chair_{p}')

  # Assign almost everyone once per date.
  for date,date_people in dates.items():
    for p in date_people:
      model.addCons( sum( var_match[date, match] for match in matches[date] if p in match ) + var_unassigned.get((date, p), 0) == 1, f'matched_{date}_{p}')

  # Count unassigned.
  for o in settings.organizers:
    model.addCons( sum( var_unassigned.get((date,o), 0) for date in dates ) == sum( i * var_num_unassigned[i].get(o, 0) for i in UNASSIGNED ), f'unassigned_{o}')

  # Minimum number of unassigned due to number theory.
  for date,date_people in dates.items():
    r = len(date_people) % settings.sizes[date]
    if r > 0:
      model.addCons( sum( var_unassigned.get((date,o), 0) for o in settings.organizers ) / r +
        sum( var for key,var in var_match.items() if key[0] == date and len(key[1]) < settings.sizes[date] ) >= 1, f'number_theory_{date}')

  # Objective
  model.setObjective(
    penalties['role'] * (sum(var_too_many_role.values()) + sum(var_too_few_role.values())) +
    penalties['same-group'] * sum(var_count_same_group.values()) +
    penalties['same-chair'] * sum(var_count_same_chair.values()) +
    penalties['smaller-match'] * sum( var for key,var in var_match.items() if settings.sizes[key[0]] > len(key[1]) ) +
    sum( penalties[f'unassigned-{i}'] * sum(var_num_unassigned[i].values()) for i in UNASSIGNED ) +
    penalties['1-years-ago']/2 * sum( var_count_meet.get(frozenset((p1, p2)), 0) for p1 in all_people for p2 in all_people[p1].get_history(1) ) +
    penalties['2-years-ago']/2 * sum( var_count_meet.get(frozenset((p1, p2)), 0) for p1 in all_people for p2 in all_people[p1].get_history(2) ) +
    penalties['3-years-ago']/2 * sum( var_count_meet.get(frozenset((p1, p2)), 0) for p1 in all_people for p2 in all_people[p1].get_history(3) )
  )

  model.writeProblem('debug.lp')
  model.setParam('propagating/probing/maxprerounds', 0)
  model.setHeuristics(pyscipopt.SCIP_PARAMSETTING.AGGRESSIVE)
  model.optimize()

  sol = model.getBestSol()

  if sol is None or model.getPrimalbound() > 1.0e15:
    print(f'No feasible solution found!')
    sys.exit(1)

  print('Penalties:')
  for key,var in var_too_many_role.items():
    val = model.getSolVal(sol, var)
    if val > 0.5:
      plural = 's' if val > 1.5 else ''
      print(f'  ${penalties["role"] * int(round(val, 0))}: {all_people[key[0]].fullname} meets {int(round(val, 0))} {key[1]}{plural} too many.')
  for key,var in var_too_many_role.items():
    val = model.getSolVal(sol, var)
    if val > 0.5:
      plural = 's' if val > 1.5 else ''
      print(f'  ${penalties["role"] * int(round(val, 0))}: {all_people[key[0]].fullname} meets {int(round(val, 0))} {key[1]}{plural} too little.')
  for p,var in var_count_same_group.items():
    val = model.getSolVal(sol, var)
    if val > 0.5:
      print(f'  ${penalties["same-group"] * int(round(val, 0))}: {all_people[p].fullname} meets {int(round(val, 0))} from own group.')
  for p,var in var_count_same_chair.items():
    val = model.getSolVal(sol, var)
    if val > 0.5:
      print(f'  ${penalties["same-chair"] * int(round(val, 0))}: {all_people[p].fullname} meets {int(round(val, 0))} from own chair.')
  for key,var in var_count_meet.items():
    if model.getSolVal(sol, var) > 0.5:
      p1, p2 = tuple(key)
      for y in [1, 2, 3]:
        penalty = penalties[f'{y}-years-ago']
        if p2 in all_people[p1].get_history(y):
          print(f'  ${penalty}: {all_people[p1].fullname} and {all_people[p2].fullname} met {y} year ago.')
  for key,var in var_match.items():
    if model.getSolVal(sol, var) > 0.5 and settings.sizes[key[0]] > len(key[1]):
      print(f'  ${penalties["smaller-match"]}: {", ".join(map(lambda x: all_people[x].fullname, key[1]) )} at <{key[0]}> is a smaller match.')
  for i in UNASSIGNED:
    penalty = penalties[f'unassigned-{i}']
    for key,var in var_num_unassigned[i].items():
      if model.getSolVal(sol, var) > 0.5:
        print(f'  ${penalty}: {all_people[key].fullname} was not assigned {i} times.')
  
  for date in dates:
    print(f'Matches at <{date}>:')
    for match in matches[date]:
      if model.getSolVal(sol, var_match[date, match]) > 0.5:
        s = [ all_people[p].fullname for p in match ]
        print(f'  {" 🧑‍🤝‍🧑 ".join(s)}')

  if results_file_name is not None:
    results = { 'solution': {} }
    for date in dates:
      results['solution'][date] = []
      for match in matches[date]:
        if model.getSolVal(sol, var_match[date, match]) > 0.5:
          results['solution'][date].append( list(match) )
    with open(results_file_name, 'w') as fp:
      fp.write(json.dumps(results, indent=2) + '\n')

