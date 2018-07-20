"""
  Harness for handling function calls including Multi-fidelity.
  -- kandasamy@cs.cmu.edu
  -- shulij@andrew.cmu.edu
"""
from __future__ import division

# pylint: disable=invalid-name
# pylint: disable=abstract-class-little-used

from builtins import object
from argparse import Namespace
import numpy as np
# Local imports
from ed.domains import EuclideanDomain
from ed.ed_utils import EVAL_ERROR_CODE
from utils.general_utils import map_to_cube, map_to_bounds

_FIDEL_TOL = 1e-2


class CalledMultiFidelOnSingleFidelCaller(Exception):
  """ An exception to handle calling multi-fidelity functions on single-fidelity
      callers.
  """
  def __init__(self, func_caller):
    """ Constructor. """
    err_msg = ('FunctionCaller %s is not a multi-fidelity caller. ' + \
               'Please use eval_single or eval_multiple.')%(str(func_caller))
    super(CalledMultiFidelOnSingleFidelCaller, self).__init__(err_msg)


class FunctionCaller(object):
  """ Function Caller class. """
  # pylint: disable=attribute-defined-outside-init

  # Methods needed for construction and set up ------------------------------------------
  def __init__(self, func, domain, descr='',
               argmax=None, maxval=None, argmin=None, minval=None,
               noise_type='no_noise', noise_scale=None,
               fidel_space=None, fidel_cost_func=None, fidel_to_opt=None):
    # pylint: disable=too-many-arguments
    """ Constructor. """
    self.func = func
    self.domain = domain
    self.descr = descr
    self.argmax = argmax
    self.maxval = maxval
    self.argmin = argmin
    self.minval = minval
    self._set_up_noise(noise_type, noise_scale)
    self._mf_set_up(fidel_space, fidel_cost_func, fidel_to_opt)

  def _set_up_noise(self, noise_type, noise_scale):
    """ Sets up noise. """
    self.noise_type = noise_type
    if noise_type == 'no_noise':
      self._is_noisy = False
      self.noise_scale = None
    else:
      self._is_noisy = True
      self.noise_scale = noise_scale
      if noise_type == 'gauss':
        self.noise_adder_single = lambda: self.noise_scale * np.random.normal()
        self.noise_adder_multiple = \
          lambda num_samples: self.noise_scale * np.random.normal((num_samples,))
      elif noise_type == 'uniform':
        self.noise_adder_single = lambda: self.noise_scale * (np.random.random() - 0.5)
        self.noise_adder_multiple = \
          lambda num_samples: self.noise_scale * (np.random.normal((num_samples,)) - 0.5)
      else:
        raise NotImplementedError(('Not implemented %s noise yet')%(self.noise_type))

  def _mf_set_up(self, fidel_space, fidel_cost_func, fidel_to_opt):
    """ Sets up multi-fidelity. """
    if any([elem is None for elem in [fidel_space, fidel_cost_func, fidel_to_opt]]):
      # If any of these are None, assert that all of them are. Otherwise through an
      # error.
      try:
        assert fidel_space is None
        assert fidel_cost_func is None
        assert fidel_to_opt is None
      except AssertionError:
        raise ValueError('Either all fidel_space, fidel_cost_func, and fidel_to_opt' +
                         'should be None or should be not-None')
      self._is_mf = False
    else:
      self.fidel_space = fidel_space
      self.fidel_cost_func = fidel_cost_func
      self.fidel_to_opt = fidel_to_opt
      self._is_mf = True

  def is_noisy(self):
    """ Returns true if noisy. """
    return self._is_noisy

  def is_mf(self):
    """ Returns True if this is multi-fidelity. """
    return self._is_mf

  def is_fidel_to_opt(self, fidel):
    """ Returns True if fidel is the fidel_to_opt. Naively tests for equality, but can
        be overridden by a child class. """
    if not self.is_mf():
      raise CalledMultiFidelOnSingleFidelCaller()
    return all(fidel == self.fidel_to_opt)

  # Evaluation --------------------------------------------------------------------------
  def _eval_single_common_wrap_up(self, true_val, qinfo, noisy, caller_eval_cost):
    """ Wraps up the evaluation by adding noise and adding info to qinfo.
        Common to both single and mutli-fidelity eval functions.
    """
    if true_val == EVAL_ERROR_CODE:
      val = EVAL_ERROR_CODE
    elif noisy and self.is_noisy():
      val = true_val + self.noise_adder_single()
    else:
      val = true_val
    # put everything into qinfo
    qinfo = Namespace() if qinfo is None else qinfo
    qinfo.true_val = true_val
    qinfo.val = val
    qinfo.caller_eval_cost = caller_eval_cost
    return val, qinfo

  def _get_true_val_from_func_at_point(self, point):
    """ Returns the true value from the function. Can be overridden by child class if
        func is represented differently. """
    return float(self.func(point))

  def _get_true_val_from_func_at_fidel_point(self, fidel, point):
    """ Returns the true value from the function. Can be overridden by child class if
        func is represented differently. """
    return float(self.func(fidel, point))

  # Single fidelity evaluations --------------------------------------------
  def eval_single(self, point, qinfo=None, noisy=True):
    """ Evaluates func at a single point point. If the function_caller is noisy by
        default, we can obtain a noiseless evaluation by setting noisy to be False.
    """
    if self.is_mf(): # if multi-fidelity call the function at fidel_to_opt
      return self.eval_at_fidel_single(self.fidel_to_opt, point, qinfo, noisy)
    else:
      true_val = self._get_true_val_from_func_at_point(point)
      val, qinfo = self._eval_single_common_wrap_up(true_val, qinfo, noisy, None)
      qinfo.point = point
      return val, qinfo

  def eval_multiple(self, points, qinfos=None, noisy=True):
    """ Evaluates multiple points. If the function_caller is noisy by
        default, we can obtain a noiseless evaluation by setting noisy to be False.
    """
    qinfos = [None] * len(points) if qinfos is None else qinfos
    ret_vals = []
    ret_qinfos = []
    for i in range(len(points)):
      val, qinfo = self.eval_single(points[i], qinfos[i], noisy)
      ret_vals.append(val)
      ret_qinfos.append(qinfo)
    return ret_vals, ret_qinfos

  # Multi-fidelity evaluations -------------------------------------------------
  def eval_at_fidel_single(self, fidel, point, qinfo=None, noisy=True):
    """ Evaluates func at a single (fidel, point). If the function_caller is noisy by
        default, we can obtain a noiseless evaluation by setting noisy to be False.
    """
    if not self.is_mf():
      raise CalledMultiFidelOnSingleFidelCaller(self)
    true_val = self._get_true_val_from_func_at_fidel_point(fidel, point)
    cost_at_fidel = self.fidel_cost_func(fidel)
    val, qinfo = self._eval_single_common_wrap_up(true_val, qinfo, noisy,
                                                  cost_at_fidel)
    qinfo.fidel = fidel
    qinfo.point = point
    qinfo.cost_at_fidel = cost_at_fidel
    return val, qinfo

  def eval_at_fidel_multiple(self, fidels, points, qinfos=None, noisy=True):
    """ Evaluates func at a multiple (fidel, point) pairs.
        If the function_caller is noisy by
        default, we can obtain a noiseless evaluation by setting noisy to be False.
    """
    qinfos = [None] * len(points) if qinfos is None else qinfos
    ret_vals = []
    ret_qinfos = []
    for i in range(len(points)):
      val, qinfo = self.eval_at_fidel_single(fidels[i], points[i], qinfos[i], noisy)
      ret_vals.append(val)
      ret_qinfos.append(qinfo)
    return ret_vals, ret_qinfos

  # Eval from qinfo
  def eval_from_qinfo(self, qinfo, *args, **kwargs):
    """ Evaluates from a qinfo object. Returns the qinfo. """
    if not hasattr(qinfo, 'fidel'):
      _, qinfo = self.eval_single(qinfo.point, qinfo, *args, **kwargs)
      return qinfo
    else:
      _, qinfo = self.eval_at_fidel_single(qinfo.fidel, qinfo.point, qinfo,
                                            *args, **kwargs)
      return qinfo

  # Cost -----------------------------------------------------------------------------
  def _get_true_cost_from_fidel_cost_func_at_fidel(self, fidel):
    """ Returns the true value from the function. Can be overridden by child class if
        fidel_cost_func is represented differently. """
    return float(self.fidel_cost_func(fidel))

  def cost_single(self, fidel):
    """ Returns the cost at a single fidelity. """
    return self._get_true_cost_from_fidel_cost_func_at_fidel(fidel)

  def cost_multiple(self, fidels):
    """ Returns the cost at multiple fidelities. """
    return [self._get_true_cost_from_fidel_cost_func_at_fidel(fidel) for fidel in fidels]

  def cost_ratio_single(self, fidel_numerator, fidel_denominator=None):
    """ Returns the cost ratio. If fidel_denominator is None, we set it to be
        fidel_to_opt.
    """
    if fidel_denominator is None:
      fidel_denominator = self.fidel_to_opt
    return self.cost_single(fidel_numerator) / self.cost_single(fidel_denominator)

  def cost_ratio_multiple(self, fidels_numerator, fidel_denominator=None):
    """ Returns the cost ratio for multiple fidels. If fidel_denominator is None,
        we set it to be fidel_to_opt.
    """
    if fidel_denominator is None:
      fidel_denominator = self.fidel_to_opt
    numerator_costs = self.cost_multiple(fidels_numerator)
    denom_cost = self.cost_single(fidel_denominator)
    ret = [x/denom_cost for x in numerator_costs]
    return ret

  # Other methods ---------------------------------------------------------------------
  def get_candidate_fidels(self, domain_point, filter_by_cost=True, *args, **kwargs):
    """ Returns candidate fidelities at domain_point.
        If filter_by_cost is true returns only those for which cost is larger than
        fidel_to_opt.
    """
    if not self.is_mf():
      raise CalledMultiFidelOnSingleFidelCaller(self)
    return self._child_get_candidate_fidels(domain_point, filter_by_cost,
                                            *args, **kwargs)

  def _child_get_candidate_fidels(self, domain_point, filter_by_cost=True,
                                  *args, **kwargs):
    """ Returns candidate fidelities at domain_point for the child class.
        If filter_by_cost is true returns only those for which cost is larger than
        fidel_to_opt.
    """
    raise NotImplementedError('Implement in a child class.')

  def get_candidate_fidels_and_cost_ratios(self, domain_point, filter_by_cost=True,
                                           *args, **kwargs):
    """ Returns candidate fidelities and the cost ratios.
        If filter_by_cost is true returns only those for which cost is larger than
        fidel_to_opt.
    """
    candidates = self.get_candidate_fidels(domain_point, filter_by_cost=False,
                                           add_fidel_to_opt=False, *args, **kwargs)
    fidel_cost_ratios = self.cost_ratio_multiple(candidates)
    if filter_by_cost:
      filtered_idxs = np.where(np.array(fidel_cost_ratios) < 1.0)[0]
      candidates = [candidates[idx] for idx in filtered_idxs]
      fidel_cost_ratios = [fidel_cost_ratios[idx] for idx in filtered_idxs]
      # But re-add fidel_to_opt.
      candidates.append(self.fidel_to_opt)
      fidel_cost_ratios.append(1.0)
    return candidates, fidel_cost_ratios

  def get_information_gap(self, fidels):
    """ Returns the information gap w.r.t fidel_to_opt. """
    raise NotImplementedError('Implement in a child class.')


class EuclideanFunctionCaller(FunctionCaller):
  """ A function caller on Euclidean spaces. """

  def __init__(self, func, raw_domain, descr='', vectorised=False,
               to_normalise_domain=True,
               raw_argmax=None, maxval=None, raw_argmin=None, minval=None,
               noise_type='no_noise', noise_scale=None,
               raw_fidel_space=None, fidel_cost_func=None, raw_fidel_to_opt=None):
    """ Constructor. """
    # pylint: disable=too-many-arguments
    # Prelims
    if hasattr(raw_domain, '__iter__'):
      raw_domain = EuclideanDomain(raw_domain)
    if hasattr(raw_fidel_space, '__iter__'):
      raw_fidel_space = EuclideanDomain(raw_fidel_space)
    self.vectorised = vectorised
    self.domain_is_normalised = to_normalise_domain
    # Set domain and and argmax/argmin
    self.raw_domain = raw_domain
    self.raw_argmax = raw_argmax
    argmax = None if raw_argmax is None else self.get_normalised_domain_coords(raw_argmax)
    self.raw_argmin = raw_argmin
    argmin = None if raw_argmin is None else self.get_normalised_domain_coords(raw_argmin)
    domain = EuclideanDomain([[0, 1]] * raw_domain.dim) if to_normalise_domain \
             else raw_domain
    # Set fidel_space
    if raw_fidel_space is not None:
      self.raw_fidel_space = raw_fidel_space
      self.raw_fidel_to_opt = raw_fidel_to_opt
      fidel_space = EuclideanDomain([[0, 1]] * raw_fidel_space.dim) \
                    if to_normalise_domain else raw_fidel_space
      fidel_to_opt = self.get_normalised_fidel_coords(raw_fidel_to_opt)
      self.fidel_space_diam = np.linalg.norm(
        fidel_space.bounds[:, 1] - fidel_space.bounds[:, 0])
    else:
      fidel_space = None
      fidel_to_opt = None
    # Now call the super constructor
    super(EuclideanFunctionCaller, self).__init__(func=func, domain=domain, descr=descr,
                 argmax=argmax, maxval=maxval, argmin=argmin, minval=minval,
                 noise_type=noise_type, noise_scale=noise_scale,
                 fidel_space=fidel_space, fidel_cost_func=fidel_cost_func,
                 fidel_to_opt=fidel_to_opt)

  def is_fidel_to_opt(self, fidel):
    """ Returns True if fidel is the fidel_to_opt. """
    return np.linalg.norm(fidel - self.fidel_to_opt) < _FIDEL_TOL * self.fidel_space_diam

  # Methods required for normalising coordinates -----------------------------------------
  def get_normalised_fidel_coords(self, Z):
    """ Maps points in the original fidelity space to the cube. """
    if self.domain_is_normalised:
      return map_to_cube(Z, self.raw_fidel_space.bounds)
    else:
      return Z

  def get_normalised_domain_coords(self, X):
    """ Maps points in the original domain to the cube. """
    if self.domain_is_normalised:
      return map_to_cube(X, self.raw_domain.bounds)
    else:
      return X

  def get_normalised_fidel_domain_coords(self, Z, X):
    """ Maps points in the original space to the cube. """
    ret_Z = None if Z is None else self.get_normalised_fidel_coords(Z)
    ret_X = None if X is None else self.get_normalised_domain_coords(X)
    return ret_Z, ret_X

  def get_raw_fidel_coords(self, Z):
    """ Maps points from the fidelity space cube to the original space. """
    if self.domain_is_normalised:
      return map_to_bounds(Z, self.raw_fidel_space.bounds)
    else:
      return Z

  def get_raw_domain_coords(self, X):
    """ Maps points from the domain cube to the original space. """
    if self.domain_is_normalised:
      return map_to_bounds(X, self.raw_domain.bounds)
    else:
      return X

  def get_raw_fidel_domain_coords(self, Z, X):
    """ Maps points from the cube to the original spaces. """
    ret_Z = None if Z is None else self.get_raw_fidel_coords(Z)
    ret_X = None if X is None else self.get_raw_domain_coords(X)
    return ret_Z, ret_X

  # Override _get_true_val_from_func_at_point and _get_true_val_from_func_at_fidel_point
  # so as to account for normalisation of the domain and/or fidel_space
  def _get_true_val_from_func_at_point(self, point):
    """ Evaluates func by first unnormalising point. """
    raw_dom_coords = self.get_raw_domain_coords(point)
    assert self.raw_domain.is_a_member(raw_dom_coords)
    if self.vectorised:
      raw_dom_coords = raw_dom_coords.reshape((-1, 1))
    return float(self.func(raw_dom_coords))

  def _get_true_val_from_func_at_fidel_point(self, fidel, point):
    """ Evaluates func by first unnormalising point. """
    raw_fidel_coords = self.get_raw_fidel_coords(fidel)
    assert self.raw_fidel_space.is_a_member(raw_fidel_coords)
    raw_dom_coords = self.get_raw_domain_coords(point)
    assert self.raw_domain.is_a_member(raw_dom_coords)
    if self.vectorised:
      raw_dom_coords = raw_dom_coords.reshape((-1, 1))
      raw_fidel_coords = raw_fidel_coords.reshape((-1, 1))
    return float(self.func(self.get_raw_fidel_coords(fidel),
                           self.get_raw_domain_coords(point)))

  def _get_true_cost_from_fidel_cost_func_at_fidel(self, fidel):
    """ Evaluates fidel_cost_func by unnormalising fidel. """
    raw_fidel_coords = self.get_raw_fidel_coords(fidel)
    assert self.raw_fidel_space.is_a_member(raw_fidel_coords)
    if self.vectorised:
      raw_fidel_coords = raw_fidel_coords.reshape((-1, 1))
    return float(self.fidel_cost_func(raw_fidel_coords))

  def _child_get_candidate_fidels(self, domain_point, filter_by_cost=True,
                                  *args, **kwargs):
    """ Returns candidate fidelities at domain_point.
        If filter_by_cost is true returns only those for which cost is larger than
        fidel_to_opt.
    """
    if self.fidel_space.dim == 1:
      norm_candidates = np.linspace(0, 1, 100).reshape((-1, 1))
    elif self.fidel_space.dim == 2:
      num_per_dim = 25
      norm_candidates = (np.indices((num_per_dim, num_per_dim)).reshape(2, -1).T + 0.5) \
                        / float(num_per_dim)
    elif self.fidel_space.dim == 3:
      num_per_dim = 10
      cand_1 = (np.indices((num_per_dim, num_per_dim, num_per_dim)).reshape(3, -1).T
                + 0.5) / float(num_per_dim)
      cand_2 = np.random.random((1000, self.fidel_space.dim))
      norm_candidates = np.vstack((cand_1, cand_2))
    else:
      norm_candidates = np.random.random((4000, self.fidel_space.dim))
    # Now unnormalise if necessary
    if self.domain_is_normalised:
      candidates = norm_candidates
    else:
      candidates = map_to_bounds(candidates, self.fidel_space.bounds)
    if filter_by_cost:
      fidel_costs = self.cost_multiple(candidates)
      filtered_idxs = np.where(np.array(fidel_costs) <
                               self.cost_single(self.fidel_to_opt))[0]
      candidates = candidates[filtered_idxs, :]
    # Finally, always add the highest fidelity
    candidates = list(candidates)
    candidates.append(self.fidel_to_opt)
    return candidates

  def get_information_gap(self, fidels):
    """ Returns distances to fidel_to_opt. """
    if not self.is_mf():
      raise CalledMultiFidelOnSingleFidelCaller(self)
    return [np.linalg.norm(fidel - self.fidel_to_opt)/self.fidel_space_diam \
            for fidel in fidels]
