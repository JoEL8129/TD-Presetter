
from TDStoreTools import StorageManager
import TDFunctions as TDF
import ast
import random
import os
import math

class presetterext:

	def __init__(self, ownerComp):
		# The component to which this extension is attached
		self.ownerComp = ownerComp

		# Reference to table DAT containing parameter names and values
		self.par_table = self.ownerComp.op('par_table')

		# Stored items (persistent across saves and re-initialization)
		storedItems = [
			{'name': 'Presets', 'default': {}, 'readOnly': False,
			 						'property': True, 'dependable': True},
			{'name': 'CurrentPresetName', 'default': None, 'readOnly': False,
			 						'property': True, 'dependable': True},
			{'name': 'PresetNames', 'default': [], 'readOnly': False,
			 						'property': True, 'dependable': True},
		]
		self.Has_changed = False
		self.stored = StorageManager(self, ownerComp, storedItems)

		# Lerp state tracking variables
		self._lerp_active = False
		self._lerp_start_values = {}
		self._lerp_target_values = {}
		self._lerp_start_time = None
		self._lerp_duration = 0.0
		self._lerp_non_numeric_params = {}
		self._lerp_target_op = None
		
		# Get reference to Execute DAT for lerp updates
		try:
			self.lerp_execute = self.ownerComp.op('lerp_execute')
		except Exception:
			self.lerp_execute = None

		# Setup parameters
		#self.SetupPars()

		# Update preset names list
		self.UpdateInfo()
		self.UpdatePresetNames()



	def _read_pars_from_table(self):
		"""
		Read parameter names and values from the table DAT.
		Skips first row (header).
		Returns dict: {par_name: value, ...}
		"""
		return self._read_pars_from_dat_table(self.par_table)

	def GetNextPresetName(self):
		"""Find next available preset_NNN name (with 3-digit zero-padding)."""
		if not self.Presets:
			return 'preset_001'

		# Extract numbers from existing preset names
		existing_numbers = []
		for name in self.Presets.keys():
			if name.startswith('preset_'):
				try:
					# Extract number part (handles both "preset_1" and "preset_001" formats)
					num_str = name.split('_')[1]
					num = int(num_str)
					existing_numbers.append(num)
				except (ValueError, IndexError):
					pass

		if not existing_numbers:
			return 'preset_001'

		# Find next available number
		next_num = max(existing_numbers) + 1
		# Format with 3-digit zero-padding
		return f'preset_{next_num:03d}'

	def GetNextAvailableName(self, base_name):
		"""
		Get next available name by appending _001, _002, etc. if base_name exists.
		If base_name doesn't exist, return it as-is.
		"""
		if base_name not in self.Presets:
			return base_name
		
		# Name exists, find next available suffix
		suffix_num = 1
		while True:
			candidate_name = f"{base_name}_{suffix_num:03d}"
			if candidate_name not in self.Presets:
				return candidate_name
			suffix_num += 1

	def UpdatePresetNames(self):
		"""Update PresetNames list with current preset names."""
		preset_names = sorted(list(self.Presets.keys()))
		self.PresetNames = preset_names

	def UpdateInfo(self):
		"""Update Monitorstr parameter to show current preset status."""
		if self.CurrentPresetName is None:
			# No preset loaded
			display_text = "No preset loaded"
		else:
			# Preset is loaded
			if self.Has_changed:
				# Parameters have changed since loading
				display_text = f"{self.CurrentPresetName} (changed)"
			else:
				# Parameters match the preset
				display_text = self.CurrentPresetName
		
		try:
			self.ownerComp.par.Monitorstr = display_text
		except Exception:
			# Monitorstr parameter might not exist, silently fail
			pass

	def UpdateMenu(self):
		"""Update Presetmenu parameter to match CurrentPresetName."""
		try:
			preset_menu = self.ownerComp.par.Presetmenu
			if preset_menu is None:
				return
			
			# Get the value to set (None becomes 'None' for menu)
			menu_value = self.CurrentPresetName if self.CurrentPresetName is not None else 'None'
			
			# Use delayed update to avoid triggering callbacks
			# Check if menu value needs to change to avoid unnecessary updates
			current_menu_val = preset_menu.eval()
			if current_menu_val != menu_value:
				run(lambda: setattr(self.ownerComp.par, 'Presetmenu', menu_value), delayFrames=5)
		except Exception:
			# Presetmenu parameter might not exist, silently fail
			pass

	def _read_pars_from_dat_table(self, dat_table):
		"""
		Read parameter names and values from a DAT table.
		Skips first row (header).
		Returns dict: {par_name: value, ...}
		"""
		if dat_table is None:
			print("Warning: DAT table not found")
			return {}

		if dat_table.numRows <= 1:
			print("Warning: DAT table has no data rows (only header)")
			return {}

		pars_dict = {}
		# Skip first row (header), start from row 1
		for r in range(1, dat_table.numRows):
			if dat_table.numCols < 2:
				continue
			
			par_name = str(dat_table[r, 0].val).strip()
			par_value_str = str(dat_table[r, 1].val).strip()
			
			if not par_name:
				continue

			# Try to evaluate the value (handles numbers, lists, etc.)
			try:
				par_value = ast.literal_eval(par_value_str)
			except (ValueError, SyntaxError):
				# If evaluation fails, use as string
				par_value = par_value_str

			pars_dict[par_name] = par_value

		return pars_dict

	def _get_filename_without_extension(self, filepath):
		"""
		Extract filename from filepath by removing directory and file extension.
		Returns clean filename without path and extension (string).
		"""
		if not filepath:
			return ''
		
		# Extract filename from path
		filename = os.path.basename(filepath)
		
		# Remove file extension (everything after last dot)
		if '.' in filename:
			filename = os.path.splitext(filename)[0]
		
		return filename

	def _is_numeric_parameter(self, par):
		"""
		Determine if a parameter can be interpolated (is numeric).
		Returns True for numeric types, False for non-numeric types.
		Handles parGroup components (e.g., 'Tx' in XYZW group) by checking the actual value type.
		"""
		if par is None:
			return False
		
		try:
			par_style = getattr(par, 'style', '').lower()
			numeric_styles = ['float', 'int', 'rgb', 'rgba', 'xy', 'uv', 'xyz', 'xyzw']
			
			# If style is explicitly numeric, return True
			if par_style in numeric_styles:
				return True
			
			# For parGroup components (e.g., 'Tx' in XYZW group has style 'XYZW'),
			# check if the actual value is numeric
			try:
				val = par.eval()
				# Check if value is numeric (int, float, or tuple/list of numbers)
				if isinstance(val, (int, float)):
					return True
				elif isinstance(val, (list, tuple)):
					# Check if all elements are numeric
					if len(val) > 0 and all(isinstance(v, (int, float)) for v in val):
						return True
			except Exception:
				pass
			
			return False
		except Exception:
			return False

	def _cancel_lerp(self):
		"""
		Cancel any active lerp and clear lerp state variables.
		Also disables the Execute DAT if it exists.
		"""
		self._lerp_active = False
		self._lerp_start_values = {}
		self._lerp_target_values = {}
		self._lerp_start_time = None
		self._lerp_duration = 0.0
		self._lerp_non_numeric_params = {}
		self._lerp_target_op = None
		
		# Disable Execute DAT if it exists
		if self.lerp_execute is not None:
			try:
				self.lerp_execute.par.active = False
			except Exception:
				pass

	# ---------- Core Preset Functions ----------
	def SavePreset(self, name=None):
		"""
		Save current parameter values from table as a preset.
		If name is None or already exists, auto-increment.
		If Saveoverwrite is enabled (1), overwrite existing presets instead of auto-incrementing.
		"""
		# Read parameters from table
		pars_dict = self._read_pars_from_table()
		
		if not pars_dict:
			print("Warning: No parameters found in table to save")
			return None

		# Check if Saveoverwrite toggle is enabled
		save_overwrite = self.ownerComp.par.Saveoverwrite


		# Determine preset name
		if name is None:
			name = self.GetNextPresetName()
		else:
			# Check if name exists
			if name in self.Presets:
				if save_overwrite:
					# Overwrite existing preset
					print(f"Overwriting existing preset '{name}' (Saveoverwrite enabled)")
				else:
					# Get next available variant
					original_name = name
					name = self.GetNextAvailableName(name)
					if name != original_name:
						print(f"Preset name '{original_name}' already exists, using: {name}")

		# Store preset (need to copy dict for property accessor)
		presets = dict(self.Presets)
		presets[name] = pars_dict
		self.Presets = presets

		# Update preset names list
		self.UpdatePresetNames()

		# Always set current preset to the newly saved one
		self.CurrentPresetName = name
		# Reset Has_changed since we just saved the current state
		self.Has_changed = False
		self.UpdateInfo()
		self.UpdateMenu()

		print(f"Preset '{name}' saved with {len(pars_dict)} parameters")
		return name

	def SetActivePreset(self, presetname):
		"""
		Set the active preset name (does not load values).
		"""
		if presetname and presetname in self.Presets:
			self.CurrentPresetName = presetname
		else:
			self.CurrentPresetName = None
		self.UpdateInfo()
		self.UpdateMenu()

	def LoadPreset(self, presetname):
		"""
		Load preset values to the target OP.
		"""
		if not presetname or presetname not in self.Presets:
			print(f"Warning: Preset '{presetname}' not found")
			return False

		# Get target OP
		try:
			target_op = self.ownerComp.par.Targetop.eval()
		except Exception:
			print("Warning: Targetop parameter not found or invalid")
			return False

		if target_op is None:
			print("Warning: Target OP is None")
			return False

		# Get preset data
		preset_data = self.Presets[presetname]

		# Apply each parameter value
		success_count = 0
		error_count = 0

		for par_name, par_value in preset_data.items():
			try:
				# Try to get parameter
				par = target_op.par[par_name]
				if par is None:
					# Try alternative access
					par = getattr(target_op.par, par_name, None)

				if par is None:
					error_count += 1
					continue

				# Set parameter value with proper type conversion
				# Handle type mismatches (e.g., float value for int parameter)
				try:
					# Get parameter style/type
					par_style = getattr(par, 'style', '').lower()
					
					# Convert value based on parameter type
					if par_style == 'int':
						# For int parameters, convert float/string to int
						if isinstance(par_value, str):
							# Try to parse string as float first, then convert to int
							try:
								par_value = int(round(float(par_value)))
							except (ValueError, TypeError):
								par_value = int(par_value)
						elif isinstance(par_value, float):
							par_value = int(round(par_value))
						else:
							par_value = int(par_value)
					elif par_style == 'float':
						# For float parameters, ensure it's a float
						if isinstance(par_value, str):
							par_value = float(par_value)
						else:
							par_value = float(par_value)
					elif par_style == 'str':
						# For string parameters, convert to string
						par_value = str(par_value)
					
					par.val = par_value
					success_count += 1
				except (ValueError, TypeError) as e:
					# If type conversion fails, try setting as-is
					try:
						par.val = par_value
						success_count += 1
					except Exception:
						error_count += 1
						print(f"Warning: Could not set parameter '{par_name}' with value '{par_value}' (type: {type(par_value).__name__}): {e}")

			except Exception as e:
				error_count += 1
				print(f"Warning: Could not set parameter '{par_name}': {e}")
		
		print(f"Loaded preset '{presetname}': {success_count} parameters set, {error_count} errors")
		# Delay setting Has_changed to False and updating display
		# This allows time for any parameter change callbacks to complete
		def delayed_update():
			self.Has_changed = False
			self.UpdateInfo()
		run(delayed_update, delayFrames=2)
		# Also update immediately to show preset name
		self.UpdateInfo()
		return success_count > 0

	def LoadPresetWithLerp(self, presetname, lerptime):
		"""
		Load preset values to the target OP with smooth interpolation over specified time.
		Numeric parameters are interpolated, non-numeric parameters switch at the end.
		Uses absTime.seconds for timing and Execute DAT for frame-based updates.
		"""
		# Validate lerptime
		if lerptime <= 0.001:
			# Very small or zero time, fall back to instant load
			return self.LoadPreset(presetname)

		# Validate preset exists
		if not presetname or presetname not in self.Presets:
			print(f"Warning: Preset '{presetname}' not found")
			return False

		# Get target OP
		try:
			target_op = self.ownerComp.par.Targetop.eval()
		except Exception:
			print("Warning: Targetop parameter not found or invalid")
			return False

		if target_op is None:
			print("Warning: Target OP is None")
			return False

		# Cancel existing lerp if active
		if self._lerp_active:
			# Read current parameter values from target OP (these become new start values)
			# We'll capture these after cancelling
			self._cancel_lerp()

		# Get preset data
		preset_data = self.Presets[presetname]

		# Capture current parameter values from target OP for all parameters in preset
		start_values = {}
		target_values = {}
		non_numeric_params = {}

		for par_name, par_value in preset_data.items():
			try:
				# Try to get parameter
				par = target_op.par[par_name]
				if par is None:
					# Try alternative access
					par = getattr(target_op.par, par_name, None)

				if par is None:
					continue

				# Check if parameter is numeric
				if self._is_numeric_parameter(par):
					# Capture current value as start value
					try:
						current_val = par.eval()
						# Validate that we can interpolate between these values
						# For multi-component values, ensure they're lists/tuples of same length
						if isinstance(current_val, (list, tuple)) and isinstance(par_value, (list, tuple)):
							if len(current_val) == len(par_value):
								start_values[par_name] = current_val
								target_values[par_name] = par_value
						elif isinstance(current_val, (int, float)) and isinstance(par_value, (int, float)):
							start_values[par_name] = current_val
							target_values[par_name] = par_value
					except Exception:
						# Skip this parameter if we can't read current value
						continue
				else:
					# Non-numeric parameter - store to apply at end
					non_numeric_params[par_name] = par_value

			except Exception:
				# Skip this parameter if we can't access it
				continue

		# Store lerp state
		self._lerp_active = True
		self._lerp_start_values = start_values
		self._lerp_target_values = target_values
		self._lerp_non_numeric_params = non_numeric_params
		self._lerp_start_time = absTime.seconds
		self._lerp_duration = lerptime
		self._lerp_target_op = target_op

		# Enable Execute DAT if it exists
		if self.lerp_execute is not None:
			try:
				self.lerp_execute.par.active = True
			except Exception:
				pass

		# Update current preset name
		self.CurrentPresetName = presetname
		self.UpdateInfo()

		print(f"Started lerp to preset '{presetname}' over {lerptime} seconds ({len(start_values)} numeric parameters, {len(non_numeric_params)} non-numeric)")
		return True

	# ---------- Easing Functions ----------
	def _ease_linear(self, t):
		"""Linear interpolation (no easing)."""
		return t

	def _ease_in_quad(self, t):
		"""Quadratic ease in."""
		return t * t

	def _ease_out_quad(self, t):
		"""Quadratic ease out."""
		return t * (2.0 - t)

	def _ease_in_out_quad(self, t):
		"""Quadratic ease in-out."""
		if t < 0.5:
			return 2.0 * t * t
		return -1.0 + (4.0 - 2.0 * t) * t

	def _ease_in_cubic(self, t):
		"""Cubic ease in."""
		return t * t * t

	def _ease_out_cubic(self, t):
		"""Cubic ease out."""
		t -= 1.0
		return t * t * t + 1.0

	def _ease_in_out_cubic(self, t):
		"""Cubic ease in-out."""
		if t < 0.5:
			return 4.0 * t * t * t
		t = 2.0 * t - 2.0
		return 0.5 * t * t * t + 1.0

	def _ease_in_quart(self, t):
		"""Quartic ease in."""
		return t * t * t * t

	def _ease_out_quart(self, t):
		"""Quartic ease out."""
		t -= 1.0
		return 1.0 - t * t * t * t

	def _ease_in_out_quart(self, t):
		"""Quartic ease in-out."""
		if t < 0.5:
			return 8.0 * t * t * t * t
		t -= 1.0
		return 1.0 - 8.0 * t * t * t * t

	def _ease_in_quint(self, t):
		"""Quintic ease in."""
		return t * t * t * t * t

	def _ease_out_quint(self, t):
		"""Quintic ease out."""
		t -= 1.0
		return 1.0 + t * t * t * t * t

	def _ease_in_out_quint(self, t):
		"""Quintic ease in-out."""
		if t < 0.5:
			return 16.0 * t * t * t * t * t
		t -= 1.0
		return 1.0 + 16.0 * t * t * t * t * t

	def _ease_in_sine(self, t):
		"""Sine ease in."""
		return 1.0 - math.cos(t * math.pi / 2.0)

	def _ease_out_sine(self, t):
		"""Sine ease out."""
		return math.sin(t * math.pi / 2.0)

	def _ease_in_out_sine(self, t):
		"""Sine ease in-out."""
		return 0.5 * (1.0 - math.cos(math.pi * t))

	def _ease_in_expo(self, t):
		"""Exponential ease in."""
		if t == 0.0:
			return 0.0
		return math.pow(2.0, 10.0 * (t - 1.0))

	def _ease_out_expo(self, t):
		"""Exponential ease out."""
		if t >= 1.0:
			return 1.0
		return 1.0 - math.pow(2.0, -10.0 * t)

	def _ease_in_out_expo(self, t):
		"""Exponential ease in-out."""
		if t == 0.0:
			return 0.0
		if t >= 1.0:
			return 1.0
		if t < 0.5:
			return 0.5 * math.pow(2.0, 20.0 * t - 10.0)
		return 1.0 - 0.5 * math.pow(2.0, -20.0 * t + 10.0)

	def _ease_in_circ(self, t):
		"""Circular ease in."""
		return 1.0 - math.sqrt(1.0 - t * t)

	def _ease_out_circ(self, t):
		"""Circular ease out."""
		t -= 1.0
		return math.sqrt(1.0 - t * t)

	def _ease_in_out_circ(self, t):
		"""Circular ease in-out."""
		if t < 0.5:
			return 0.5 * (1.0 - math.sqrt(1.0 - 4.0 * t * t))
		t = 2.0 * t - 2.0
		return 0.5 * (math.sqrt(1.0 - t * t) + 1.0)

	def _ease_in_back(self, t):
		"""Back ease in."""
		c1 = 1.70158
		c3 = c1 + 1.0
		return c3 * t * t * t - c1 * t * t

	def _ease_out_back(self, t):
		"""Back ease out."""
		c1 = 1.70158
		c3 = c1 + 1.0
		t -= 1.0
		return 1.0 + c3 * t * t * t + c1 * t * t

	def _ease_in_out_back(self, t):
		"""Back ease in-out."""
		c1 = 1.70158
		c2 = c1 * 1.525
		if t < 0.5:
			return 0.5 * (2.0 * t) * (2.0 * t) * ((c2 + 1.0) * 2.0 * t - c2)
		t = 2.0 * t - 2.0
		return 0.5 * ((t) * t * ((c2 + 1.0) * t + c2) + 2.0)

	def _ease_in_elastic(self, t):
		"""Elastic ease in."""
		if t == 0.0:
			return 0.0
		if t >= 1.0:
			return 1.0
		c4 = (2.0 * math.pi) / 3.0
		return -math.pow(2.0, 10.0 * t - 10.0) * math.sin((t * 10.0 - 10.75) * c4)

	def _ease_out_elastic(self, t):
		"""Elastic ease out."""
		if t == 0.0:
			return 0.0
		if t >= 1.0:
			return 1.0
		c4 = (2.0 * math.pi) / 3.0
		return math.pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0

	def _ease_in_out_elastic(self, t):
		"""Elastic ease in-out."""
		if t == 0.0:
			return 0.0
		if t >= 1.0:
			return 1.0
		c5 = (2.0 * math.pi) / 4.5
		if t < 0.5:
			return -0.5 * math.pow(2.0, 20.0 * t - 10.0) * math.sin((20.0 * t - 11.125) * c5)
		return 0.5 * math.pow(2.0, -20.0 * t + 10.0) * math.sin((20.0 * t - 11.125) * c5) + 1.0

	def _ease_in_bounce(self, t):
		"""Bounce ease in."""
		return 1.0 - self._ease_out_bounce(1.0 - t)

	def _ease_out_bounce(self, t):
		"""Bounce ease out."""
		if t < 1.0 / 2.75:
			return 7.5625 * t * t
		elif t < 2.0 / 2.75:
			t -= 1.5 / 2.75
			return 7.5625 * t * t + 0.75
		elif t < 2.5 / 2.75:
			t -= 2.25 / 2.75
			return 7.5625 * t * t + 0.9375
		else:
			t -= 2.625 / 2.75
			return 7.5625 * t * t + 0.984375

	def _ease_in_out_bounce(self, t):
		"""Bounce ease in-out."""
		if t < 0.5:
			return 0.5 * self._ease_in_bounce(2.0 * t)
		return 0.5 * self._ease_out_bounce(2.0 * t - 1.0) + 0.5

	def _get_easing_function(self, method_name):
		"""
		Get the easing function by method name.
		Returns the easing function, or linear if method not found.
		"""
		easing_map = {
			'linear': self._ease_linear,
			'ease_in_quad': self._ease_in_quad,
			'ease_out_quad': self._ease_out_quad,
			'ease_in_out_quad': self._ease_in_out_quad,
			'ease_in_cubic': self._ease_in_cubic,
			'ease_out_cubic': self._ease_out_cubic,
			'ease_in_out_cubic': self._ease_in_out_cubic,
			'ease_in_quart': self._ease_in_quart,
			'ease_out_quart': self._ease_out_quart,
			'ease_in_out_quart': self._ease_in_out_quart,
			'ease_in_quint': self._ease_in_quint,
			'ease_out_quint': self._ease_out_quint,
			'ease_in_out_quint': self._ease_in_out_quint,
			'ease_in_sine': self._ease_in_sine,
			'ease_out_sine': self._ease_out_sine,
			'ease_in_out_sine': self._ease_in_out_sine,
			'ease_in_expo': self._ease_in_expo,
			'ease_out_expo': self._ease_out_expo,
			'ease_in_out_expo': self._ease_in_out_expo,
			'ease_in_circ': self._ease_in_circ,
			'ease_out_circ': self._ease_out_circ,
			'ease_in_out_circ': self._ease_in_out_circ,
			'ease_in_back': self._ease_in_back,
			'ease_out_back': self._ease_out_back,
			'ease_in_out_back': self._ease_in_out_back,
			'ease_in_elastic': self._ease_in_elastic,
			'ease_out_elastic': self._ease_out_elastic,
			'ease_in_out_elastic': self._ease_in_out_elastic,
			'ease_in_bounce': self._ease_in_bounce,
			'ease_out_bounce': self._ease_out_bounce,
			'ease_in_out_bounce': self._ease_in_out_bounce,
		}
		return easing_map.get(method_name, self._ease_linear)



	def _update_lerp(self):
		"""
		Polling-based update function for lerp interpolation.
		Called by Execute DAT each frame when lerp is active.
		Uses absTime.seconds to calculate progress and update parameters.
		"""
		# Check if lerp is still active (might have been cancelled)
		if not self._lerp_active:
			return

		# Check if target OP is still valid
		if self._lerp_target_op is None:
			self._cancel_lerp()
			return

		# Validate target OP is still accessible
		try:
			_ = self._lerp_target_op.par
		except Exception:
			# Target OP is no longer valid
			print("Warning: Target OP became invalid during lerp, cancelling")
			self._cancel_lerp()
			return

		# Calculate elapsed time and progress using absTime.seconds
		elapsed = absTime.seconds - self._lerp_start_time
		t_raw = min(elapsed / self._lerp_duration, 1.0)
		
		# Get easing method from parameter (default to linear if not set)
		easing_method = 'linear'
		try:
			lerp_method_par = self.ownerComp.par.Lerpmethods
			if lerp_method_par is not None:
				easing_method = lerp_method_par.eval()
		except Exception:
			pass
		
		# Apply easing function to t
		easing_func = self._get_easing_function(easing_method)
		t = easing_func(t_raw)

		# Apply interpolated values to numeric parameters
		success_count = 0
		error_count = 0

		for par_name in self._lerp_start_values.keys():
			try:
				# Get parameter reference
				par = self._lerp_target_op.par[par_name]
				if par is None:
					par = getattr(self._lerp_target_op.par, par_name, None)

				if par is None:
					error_count += 1
					continue

				# Get start and target values
				start_val = self._lerp_start_values[par_name]
				target_val = self._lerp_target_values[par_name]

				# Interpolate based on value type (works for both regular params and parGroup components)
				try:
					# Check if values are single numbers or multi-component
					if isinstance(start_val, (int, float)) and isinstance(target_val, (int, float)):
						# Single numeric value interpolation (works for float, int, and parGroup components)
						start_float = float(start_val)
						target_float = float(target_val)
						interp_val = start_float + (target_float - start_float) * t
						
						# Check if parameter expects int (for int parameters)
						par_style = getattr(par, 'style', '').lower()
						if par_style == 'int':
							par.val = int(round(interp_val))
						else:
							# For float and parGroup components, set as float
							# TouchDesigner will handle the conversion automatically
							par.val = interp_val
						success_count += 1
						
					elif isinstance(start_val, (list, tuple)) and isinstance(target_val, (list, tuple)):
						# Multi-component interpolation (RGB, RGBA, XYZ, XYZW, etc.)
						if len(start_val) == len(target_val):
							try:
								interp_vals = [float(start_val[i]) + (float(target_val[i]) - float(start_val[i])) * t for i in range(len(start_val))]
								par.val = tuple(interp_vals)
								success_count += 1
							except (ValueError, TypeError):
								error_count += 1
						else:
							error_count += 1
					else:
						# Mismatched types - try to convert both to float
						try:
							start_float = float(start_val)
							target_float = float(target_val)
							interp_val = start_float + (target_float - start_float) * t
							par.val = interp_val
							success_count += 1
						except (ValueError, TypeError):
							error_count += 1

				except Exception:
					error_count += 1
					# Silently continue - don't spam errors

			except Exception:
				error_count += 1
				# Silently continue

		# Check if lerp is complete
		if t >= 1.0:
			# Lerp complete - apply non-numeric parameters and cleanup
			self._apply_non_numeric_params()
			self._complete_lerp()

	def _apply_non_numeric_params(self):
		"""
		Apply non-numeric parameters (strings, menus, toggles) at the end of lerp.
		"""
		if self._lerp_target_op is None:
			return

		success_count = 0
		error_count = 0

		for par_name, par_value in self._lerp_non_numeric_params.items():
			try:
				# Try to get parameter
				par = self._lerp_target_op.par[par_name]
				if par is None:
					par = getattr(self._lerp_target_op.par, par_name, None)

				if par is None:
					error_count += 1
					continue

				# Apply value with type conversion (same logic as LoadPreset)
				try:
					par_style = getattr(par, 'style', '').lower()

					if par_style == 'int':
						if isinstance(par_value, str):
							try:
								par_value = int(round(float(par_value)))
							except (ValueError, TypeError):
								par_value = int(par_value)
						elif isinstance(par_value, float):
							par_value = int(round(par_value))
						else:
							par_value = int(par_value)
					elif par_style == 'float':
						if isinstance(par_value, str):
							par_value = float(par_value)
						else:
							par_value = float(par_value)
					elif par_style == 'str':
						par_value = str(par_value)

					par.val = par_value
					success_count += 1
				except (ValueError, TypeError) as e:
					try:
						par.val = par_value
						success_count += 1
					except Exception:
						error_count += 1

			except Exception:
				error_count += 1

		if error_count > 0:
			print(f"Applied {success_count} non-numeric parameters, {error_count} errors")

	def _complete_lerp(self):
		"""
		Complete the lerp process - cleanup and update state.
		"""
		# Reset Has_changed since we just loaded the preset
		def delayed_update():
			self.Has_changed = False
			self.UpdateInfo()
		run(delayed_update, delayFrames=2)
		self.UpdateInfo()

		# Clear lerp state and disable Execute DAT
		self._cancel_lerp()

		print("Lerp completed")

	def DeletePreset(self, presetname):
		"""
		Delete a preset from storage.
		"""
		if not presetname or presetname not in self.Presets:
			print(f"Warning: Preset '{presetname}' not found")
			return False

		# Remove from presets dict
		presets = dict(self.Presets)
		del presets[presetname]
		self.Presets = presets

		# Update preset names list
		self.UpdatePresetNames()

		# Clear current preset if it was deleted
		if self.CurrentPresetName == presetname:
			self.CurrentPresetName = None
			self.UpdateInfo()
			self.UpdateMenu()

		print(f"Preset '{presetname}' deleted")
		return True

	def DeleteAllPresets(self):
		"""
		Delete all presets from storage.
		"""
		preset_count = len(self.Presets)
		
		if preset_count == 0:
			print("No presets to delete")
			return False

		# Clear all presets
		self.Presets = {}

		# Clear current preset name
		self.CurrentPresetName = None
		self.UpdateInfo()
		self.UpdateMenu()

		# Update preset names list
		self.UpdatePresetNames()

		print(f"Deleted all {preset_count} presets")
		return True

	# ---------- Callback Handlers ----------
	def OnPresetmenu(self, par):
		"""Callback for Presetmenu - updates CurrentPresetName and loads preset when menu selection changes."""
		try:
			menu_val = par.eval()
			if menu_val and menu_val != 'None':
				# Update CurrentPresetName to match menu selection
				self.CurrentPresetName = menu_val
				# Check if Lerp toggle is enabled
				try:
					lerp_enabled = self.ownerComp.par.Lerp.eval()
					if lerp_enabled:
						# Get lerp time and use lerp loading
						lerptime = self.ownerComp.par.Lerptime
						self.LoadPresetWithLerp(menu_val, lerptime)
					else:
						# Load the preset values to target OP (instant)
						self.LoadPreset(menu_val)
				except Exception:
					# Lerp parameters might not exist, fall back to instant load
					self.LoadPreset(menu_val)
			else:
				# 'None' selected
				self.CurrentPresetName = None
				self.UpdateInfo()
		except Exception as e:
			print(f"Warning: Could not update preset from menu: {e}")

	def OnSave(self, par):
		"""Callback for Save button - saves preset with auto-increment naming."""
		# Get preset name from Savename parameter if available
		preset_name = None
		try:
			savename_par = self.ownerComp.par.Savename
			if savename_par:
				savename_val = savename_par.eval()
				if savename_val and savename_val.strip():
					preset_name = savename_val.strip()
		except Exception:
			pass
		
		# If Savename is empty, use None to trigger auto-increment
		# SavePreset will handle auto-increment if preset_name already exists
		saved_name = self.SavePreset(preset_name)
		if saved_name:
			# Update current preset
			self.SetActivePreset(saved_name)

	def OnSaveas(self, par):
		"""Callback for Saveas button - placeholder (functionality outside script)."""
		# Placeholder - functionality handled outside script
		pass

	def OnDelete(self, par):
		"""Callback for Delete button - deletes currently selected preset."""
		# Get current preset from Presetmenu
		preset_name = None
		try:
			preset_menu = self.ownerComp.par.Presetmenu
			if preset_menu:
				menu_val = preset_menu.eval()
				if menu_val and menu_val != 'None':
					preset_name = menu_val
		except Exception:
			pass

		if preset_name:
			self.DeletePreset(preset_name)
		else:
			print("Warning: No preset selected to delete")

	def OnDeleteall(self, par):
		"""Callback for Deleteall button - deletes all presets."""
		self.DeleteAllPresets()

	def OnReload(self, par):
		"""Callback for Reload button - reloads current preset values to target OP."""
		# Get current preset from Presetmenu
		preset_name = None
		try:
			preset_menu = self.ownerComp.par.Presetmenu
			if preset_menu:
				menu_val = preset_menu.eval()
				if menu_val and menu_val != 'None':
					preset_name = menu_val
		except Exception:
			pass

		if preset_name:
			# Check if Lerp toggle is enabled
			try:
				lerp_enabled = self.ownerComp.par.Lerp.eval()
				if lerp_enabled:
					# Get lerp time and use lerp loading
					lerptime = self.ownerComp.par.Lerptime
					self.LoadPresetWithLerp(preset_name, lerptime)
				else:
					# Load the preset values to target OP (instant)
					self.LoadPreset(preset_name)
			except Exception:
				# Lerp parameters might not exist, fall back to instant load
				self.LoadPreset(preset_name)
		else:
			print("Warning: No preset selected to reload")

	def OnRandomize(self, par):
		"""Callback for Randomize button - randomizes parameters on targetOp based on par_table."""
		# Get target OP
		try:
			target_op = self.ownerComp.par.Targetop.eval()
		except Exception:
			print("Warning: Targetop parameter not found or invalid")
			return

		if target_op is None:
			print("Warning: Target OP is None")
			return

		# Read parameter names from par_table
		if self.par_table is None:
			print("Warning: par_table DAT not found")
			return

		if self.par_table.numRows <= 1:
			print("Warning: par_table has no data rows (only header)")
			return

		success_count = 0
		error_count = 0

		# Skip first row (header), start from row 1
		for r in range(1, self.par_table.numRows):
			if self.par_table.numCols < 1:
				continue
			
			par_name = str(self.par_table[r, 0].val).strip()
			
			if not par_name:
				continue

			try:
				# Try to get parameter on targetOp
				par_ref = target_op.par[par_name]
				if par_ref is None:
					# Try alternative access
					par_ref = getattr(target_op.par, par_name, None)

				if par_ref is None:
					error_count += 1
					continue

				# Get min and max values
				minv = par_ref.normMin
				maxv = par_ref.normMax
				
				# Generate random value
				rand_val = random.uniform(minv, maxv)
				par_ref.val = rand_val
				success_count += 1

			except Exception as e:
				error_count += 1
				print(f"Warning: Could not randomize parameter '{par_name}': {e}")

		print(f"Randomized {success_count} parameters, {error_count} errors")

	def OnFilesave(self, par):
		"""Callback for Filesave parameter - triggers fileOut operator to export par_table to file."""
		# Get fileOut operator reference
		try:
			fileout_op = self.ownerComp.op('fileOut')
			if fileout_op is None:
				print("Warning: fileOut operator not found")
				return
		except Exception:
			print("Warning: Could not get fileOut operator reference")
			return
		
		# Trigger the fileOut operator to write the file
		# The file path is already set via par reference in TD
		try:
			fileout_op.par.write.pulse()
			print("Preset table exported to file")
		except Exception as e:
			print(f"Error triggering fileOut: {e}")

	def OnFileload(self, par):
		"""Callback for Fileload parameter - triggers fileIn refreshpulse and imports preset from DAT table."""
		# Get fileIn operator reference
		try:
			filein_op = self.ownerComp.op('fileIn')
			if filein_op is None:
				print("Warning: fileIn operator not found")
				return
		except Exception:
			print("Warning: Could not get fileIn operator reference")
			return
		
		# Trigger refreshpulse to reload the file
		try:
			filein_op.par.refreshpulse.pulse()
		except Exception as e:
			print(f"Warning: Could not trigger refreshpulse on fileIn: {e}")
			return
		
		# Wait a frame for the file to load, then read the table
		def delayed_import():
			try:
				# Read the fileIn DAT table (it should be the same structure as par_table)
				filein_table = filein_op
				if filein_table is None:
					print("Warning: fileIn operator has no DAT table")
					return
				
				# Read parameters from the fileIn table
				pars_dict = self._read_pars_from_dat_table(filein_table)
				
				if not pars_dict:
					print("Warning: No parameters found in imported file")
					return
				
				# Get filename from fileIn.par.file and extract preset name
				try:
					filepath = filein_op.par.file.eval()
					preset_name = self._get_filename_without_extension(filepath)
					
					if not preset_name:
						print("Warning: Could not extract preset name from file path")
						return
				except Exception:
					print("Warning: Could not get file path from fileIn.par.file")
					return
				
				# Save the imported data as a preset (similar to SavePreset logic)
				# Check if Saveoverwrite toggle is enabled
				save_overwrite = self.ownerComp.par.Saveoverwrite
				
				# Determine preset name (handle overwrite logic)
				if preset_name in self.Presets:
					if save_overwrite:
						# Overwrite existing preset
						print(f"Overwriting existing preset '{preset_name}' (Saveoverwrite enabled)")
					else:
						# Get next available variant
						original_name = preset_name
						preset_name = self.GetNextAvailableName(preset_name)
						if preset_name != original_name:
							print(f"Preset name '{original_name}' already exists, using: {preset_name}")
				
				# Store preset (need to copy dict for property accessor)
				presets = dict(self.Presets)
				presets[preset_name] = pars_dict
				self.Presets = presets
				
				# Update preset names list
				self.UpdatePresetNames()
				
				# Always set current preset to the newly imported one
				self.CurrentPresetName = preset_name
				# Reset Has_changed since we just imported the state
				self.Has_changed = False
				self.UpdateInfo()
				self.UpdateMenu()
				
				print(f"Preset '{preset_name}' imported from file with {len(pars_dict)} parameters")
				self.ownerComp.par.Reload.pulse()	
			except Exception as e:
				print(f"Error importing preset from file: {e}")
		
		# Delay the import to allow fileIn to finish loading
		run(delayed_import, delayFrames=5)
		

