#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
\descr: List of the clustering algorithms and their evaluation functions
	to be executed by the benchmark

	Execution function for each algorithm must be named: exec<Algname>
	Evaluation function for each algorithm must be named: eval<Algname>

\author: (c) Artem Lutov <artem@exascale.info>
\organizations: eXascale Infolab <http://exascale.info/>, Lumais <http://www.lumais.com/>, ScienceWise <http://sciencewise.info/>
\date: 2015-07
"""

from __future__ import print_function  # Required for stderr output, must be the first import
import os
import shutil
import glob
#import subprocess
import sys
# Add algorithms modules
#sys.path.insert(0, 'algorithms')  # Note: this operation might lead to ambiguity on paths resolving

#from algorithms.louvain_igraph import louvain
#from algorithms.randcommuns import randcommuns
from benchcore import *
from benchutils import *


from sys import executable as PYEXEC  # Full path to the current Python interpreter

# Note: '/' is required in the end of the dir to evaluate whether it is already exist and distinguish it from the file
_ALGSDIR = 'algorithms/'  # Default directory of the benchmarking algorithms
_RESDIR = 'results/'  # Final accumulative results of .mod, .nmi and .rcp for each algorithm, specified RELATIVE to _ALGSDIR
_CLSDIR = 'clusters/'  # Clusters directory for the resulting clusters of algorithms execution
_MODDIR = 'mod/'
_NMIDIR = 'nmi/'
_EXTLOG = '.log'
_EXTERR = '.err'
_EXTEXECTIME = '.rcp'  # Resource Consumption Profile
_EXTCLNODES = '.cnl'  # Clusters (Communities) Nodes Lists
#_extmod = '.mod'
_EXECNMI = './gecmi'  # Binary for NMI evaluation
_SEPINST = '^'  # Network instances separator, must be a char
_SEPPARS = '!'  # Network parameters separator, must be a char
_SEPPATHID = '#'  # Network path id separator (to distinguish files with the same name from different dirs), must be a char
_PATHID_FILE = 'f'  # File marker of the pathid (input file specified directly without the embracing dir), must be a char
# Note: '.' is used as network shuffles separator
#_netshuffles = 4  # Number of shuffles for each input network for Louvain_igraph (non determenistic algorithms)


def	preparePath(taskpath):
	"""Create the path if required, otherwise move existent data to backup.
	All itnstances and shuffles of each network are handled all together and only once,
	even on calling this function for each shuffle.
	NOTE: To process files starting with taskpath, it should not contain '/' in the end

	taskpath  - the path to be prepared
	"""
	# Backup existent files & dirs with such base only if this path exists and is not empty
	# ATTENTION: do not use basePathExists(taskpath) here to avoid movement to the backup
	# processing paths when xxx.mod.net is processed before the xxx.net (have the same base)
	if os.path.exists(taskpath) and not dirempty(taskpath):
		# Extract main task base name from instances, shuffles and params, and process them all together
		mainpath, name = os.path.split(taskpath)
		if name:
			# Extract name suffix, skipping the extension
			name = os.path.splitext(name)[0]
			# Find position of the separator symbol, considering that it can't be begin of the name
			pos = filter(lambda x: x >= 1, [name.rfind(c) for c in (_SEPINST, _SEPPARS)])  # Note: reverse direction to skip possible separator symbols in the name itself
			if pos:
				pos = min(pos)
				name = name[:pos]
			mainpath = '/'.join((mainpath, name))  # Note: reverse direction to skip possible separator symbols in the name itself
		# Extract endings of multiple instances
		parts = mainpath.rsplit(_SEPINST, 1)
		if len(parts) >= 2:
			try:
				int(parts[1])
			except ValueError:
				# It's not an instance name
				pass
			else:
				# Instance name
				mainpath = parts[0]
		backupPath(mainpath, True)
	# Create target path if not exists
	if not os.path.exists(taskpath):
		os.makedirs(taskpath)


def evalGeneric(execpool, evalname, algname, basefile, measdir, timeout, evalfile, aggregate=None, pathid='', tidy=True):
	"""Generic evaluation on the specidied file
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	evalname  - evaluating measure name
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
		Note: basefile itself never contains pathid
	measdir  - measure-identifying directory to store results
	timeout  - execution timeout for this task
	evalfile  - file evaluation callback to define evaluation jobs, signature:
		evalfile(jobs, cfile, jobname, task, taskoutp, ijobsuff, logsbase)
	aggregate  - aggregation callback, called on the task completion, signature: aggregate(task)
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs.
		Note: pathid includes pathid separator
	tidy  - delete previously existent resutls. Must be False if a few apps output results into the same dir
	"""
	assert execpool and basefile and evalname and algname, "Parameters must be defined"
	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
	# Fetch the task name and chose correct network filename
	taskcapt = os.path.splitext(os.path.split(basefile)[1])[0]  # Name of the basefile (network or ground-truth clusters)
	ishuf = os.path.splitext(taskcapt)[1]  # Separate shuffling index (with pathid if exists) if exists
	assert taskcapt and not ishuf, 'The base file name must exists and should not be shuffled'
	# Define index of the task suffix (identifier) start
	tcapLen = len(taskcapt)  # Note: it never contains pathid

	# Make dirs with logs & errors
	# Directory of resulting community structures (clusters) for each network
	# Note:
	#  - consider possible parameters of the executed algorithm, embedded into the dir names with _SEPPARS
	#  - base file never has '.' in the name except exception, so ext extraction is applicable
	#print('basefile: {}, taskcapt: {}'.format(basefile, taskcapt))

	# Resource consumption profile file name
	rcpoutp = ''.join((_RESDIR, algname, '/', evalname, _EXTEXECTIME))
	task = Task(name='_'.join((evalname, taskcapt, pathid, algname)), ondone=aggregate)  # , params=EvalState(taskcapt, )
	jobs = []
	# Traverse over directories of clusters corresponding to the base network
	for clsbase in glob.iglob(''.join((_RESDIR, algname, '/', _CLSDIR, escapePathWildcards(taskcapt), '*'))):
		# Skip execution of log files, leaving only dirs
		if not os.path.isdir(clsbase):
			continue
		clsname = os.path.split(clsbase)[1]  # Processing clusters dir, which base name of the job, id part of the task name
		clsnameLen = len(clsname)

		# Skip cases when processing clusters does not have expected pathid
		if pathid and not clsname.endswith(pathid):
			continue
		# Skip cases whtn processing clusters have unexpected pathid
		elif not pathid:
			icnpid = clsname.rfind('#')  # Index of pathid in clsname
			if icnpid != -1 and icnpid + 1 < clsnameLen:
				# Check whether this is a valid pathid considering possible pathid file mark
				if clsname[icnpid + 1] == _PATHID_FILE:
					icnpid += 1
				# Validate pathid
				try:
					int(clsname[icnpid + 1:])
				except ValueError as err:
					# This is not the pathid, or this pathid has invalid format
					print('WARNING, invalid pathid or file name uses pathid separator: {}. Exception: {}.'
						' The processing is continued assuming that pathid is not exist for this file.'
						.format(clsname, err))
					# Continue processing as ordinary clusters wthout pathid
				else:
					# Skip this clusters having unexpected pathid
					continue
		icnpid = clsnameLen - len(pathid)  # Index of pathid in clsname

		# Filter out unexpected instances of the network (when then instance without id is processed)
		if clsnameLen > tcapLen and clsname[tcapLen] == _SEPINST:
			continue

		# Fetch shuffling index if exists
		ish = clsname[:icnpid].rfind('.') + 1  # Note: reverse direction to skip possible separator symbols in the name itself
		shuffle = clsname[ish:icnpid] if ish else ''
		# Validate shufflng index
		if shuffle:
			try:
				int(shuffle)
			except ValueError as err:
				print('WARNING, invalid shuffling index or it represents a part of the filename: "{}". Exception: {}'
					' The processing is continued assuming that sfhulling is not exist for this file.'
					.format(clsname, err))
				# Continue processing skipping such index
				shuffle = ''

		# Note: separate dir is created, because modularity is evaluated for all files in the target dir,
		# which are different granularity / hierarchy levels
		logsbase = clsbase.replace(_CLSDIR, measdir)
		# Remove previous results if exist and required
		if tidy and os.path.exists(logsbase):
			shutil.rmtree(logsbase)
		if tidy or not os.path.exists(logsbase):
			os.makedirs(logsbase)

		# Skip shuffle indicator to accumulate values from all shuffles into the single file
		taskoutp = os.path.splitext(logsbase)[0] if shuffle else logsbase
		# Recover lost pathid if required
		if shuffle and pathid:
			taskoutp += pathid
		taskoutp = '.'.join((taskoutp, evalname))  # evalext  # Name of the file with modularity values for each level
		if tidy and os.path.exists(taskoutp):
			os.remove(taskoutp)

		# Traverse over all resulting communities for each ground truth, log results
		for cfile in glob.iglob(escapePathWildcards(clsbase) + '/*'):
			if os.path.isdir(cfile):  # Skip dirs among the resulting clusters (extra/, generated by OSLOM)
				continue
			# Extract base name of the evaluating clusters level
			# Note: benchmarking algortihm output file names are not controllable and can be any, unlike the embracing folders
			jbasename = os.path.splitext(os.path.split(cfile)[1])[0]
			assert jbasename, 'The clusters name should exists'
			# Extand job caption with the executing task if not already contains and update the caption index
			jscorr = jbasename.find(clsname)
			# Corrected job suffix if required
			if jscorr == -1:
				jscorr = 0
				jbasename = '_'.join((clsname, jbasename))
			jobcapt = jbasename[jscorr + clsnameLen + 1:]  # Skip also separator symbol
			if shuffle:
				jobcapt = '_'.join((shuffle, jobcapt))
			#jobcapt = '  '.join((jbasename, clsname, pathid, basefile, '<<<', clsbase, '>>>', jobcapt))
			jobname = '_'.join((evalname, clsname, algname))  # Note: pathid can be empty
			logfilebase = '/'.join((logsbase, jbasename))
			# pathid must be part of jobname, and  bun not of the jobsuff
			evalfile(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobcapt, logfilebase)
	# Run all jobs after all of them were added to the task
	if jobs:
		for job in jobs:
			try:
				execpool.execute(job)
			except StandardError as err:
				print('WARNING, "{}" job is interrupted by the exception: {}'
					.format(job.name, err), file=sys.stderr)
	else:
		print('WARNING, "{}" clusters "{}" do not exist to be evaluated'
			.format(algname, clsname), file=sys.stderr)


def evalAlgorithm(execpool, algname, basefile, measure, timeout, pathid=''):
	"""Evaluate the algorithm by the specified measure.
	NOTE: all paths are given relative to the root benchmark directory.

	execpool  - execution pool of worker processes
	algname  - a name of the algorithm being under evaluation
	basefile  - ground truth result, or initial network file or another measure-related file
	measure  - target measure to be evaluated: {nmi, nmi_s, mod}
	timeout  - execution timeout for this task
	pathid  - path id of the basefile to distinguish files with the same name located in different dirs
		Note: pathid includes pathid separator
	"""
	assert not pathid or pathid[0] == _SEPPATHID, 'pathid must include pathid separator'
	print('Evaluating {} for "{}" on base of "{}"...'.format(measure, algname, basefile))

	#evalname = None
	#if measure == 'nmi_s':
	#	# Evaluate by NMI_sum (onmi) instead of NMI_conv(gecmi)
	#	evalname = measure
	#	measure = 'nmi'
	#eaname = measure + 'Algorithm'
	#evalg = getattr(sys.modules[__name__], eaname, unknownApp(eaname))
	#if not evalname:
	#	evalg(execpool, algname, basefile, timeout)
	#else:
	#	evalg(execpool, algname, basefile, timeout, evalbin='./onmi_sum', evalname=evalname)

	def modEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobsuff, logsbase):
		"""Add modularity evaluatoin job to the current jobs
		NOTE: all paths are given relative to the root benchmark directory.

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		jobsuff  - job specific suffix after the mutual name base inherent to the task
		logsbase  - base part of the file name for the logs including errors
		"""
		#print('Starting modEvaluate with params:\t[basefile: {}]\n\tcfile: {}\n\tjobname: {}'
		#	'\n\ttask.name: {}\n\ttaskoutp: {}\n\tjobsuff: {}\n\tlogsbase: {}\n'
		#	.format(basefile, cfile, jobname, task.name, taskoutp, jobsuff, logsbase), file=sys.stderr)

		# Processing is performed from the algorithms dir
		args = ('./hirecs', '-e=../' + cfile, '../' + basefile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			result = job.proc.communicate()[0]  # Read buffered stdout
			# Find require value to be aggregated
			targpref = 'mod: '
			# Match float number
			mod = parseFloat(result[len(targpref):])[0] if result.startswith(targpref) else None
			if mod is None:
				print('ERROR, job "{}" has invalid output format. Moularity value is not found in:\n{}'
					.format(job.name, result), file=sys.stderr)
				return

			taskoutp = job.params['taskoutp']
			with open(taskoutp, 'a') as tmod:  # Append to the end
				if not os.path.getsize(taskoutp):
					tmod.write('# Q\t[ShuffleIndex_]Level\n')
					tmod.flush()
				tmod.write('{}\t{}\n'.format(mod, job.params['jobsuff']))
				# Also transfer this resutls to the embracing task if exists
				if job.task and job.task.onjobdone:
					job.task.onjobdone(job, mod)
				else:
					print('WARNING, task "{}" of job "{}" has no defined onjobdone() to aggregate results:\n{}'
						.format(job.name, result), file=sys.stderr)


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args
			, timeout=timeout, ondone=aggLevs, params={'taskoutp': taskoutp, 'jobsuff': jobsuff}
			# Output modularity to the proc PIPE buffer to be aggregated on postexec to avoid redundant files
			, stdout=PIPE, stderr=logsbase + _EXTERR))


	def nmiEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobsuff, logsbase):
		"""Add nmi evaluatoin job to the current jobs

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		jobsuff  - job specific suffix after the mutual name base inherent to the task
		logsbase  - base part of the file name for the logs including errors

		Example:
		[basefile: syntnets/networks/1K10/1K10.cnl]
		cfile: results/scp/clusters/1K10!k3/1K10!k3_1.cnl
		jobname: nmi_1K10!k3_1_scp
		task.name: nmi_1K10_scp
		taskoutp: results/scp/nmi/1K10!k3.nmi
		rcpoutp: results/scp/nmi.rcp
		jobsuff: 1
		logsbase: results/scp/nmi/1K10!k3/1K10!k3_1
		"""
		## Undate current environmental variables with LD_LIBRARY_PATH
		ldpname = 'LD_LIBRARY_PATH'
		ldpval = '.'
		ldpath = os.environ.get(ldpname, '')
		if not ldpath or not envVarDefined(value=ldpval, evar=ldpath):
			if ldpath:
				ldpath = ':'.join((ldpath, ldpval))
			else:
				ldpath = ldpval
			os.environ[ldpname] = ldpath

		# Processing is performed from the algorithms dir
		args = ('../exectime', '-o=../' + rcpoutp, '-n=' + jobname, './gecmi', '../' + basefile, '../' + cfile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0]
				nmi = float(result)  # Read buffered stdout
			except ValueError:
				print('ERROR, nmi evaluation failed for the job "{}": {}'
					.format(job.name, result), file=sys.stderr)
			else:
				taskoutp = job.params['taskoutp']
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.path.getsize(taskoutp):
						tnmi.write('# NMI\t[shuffle_]level\n')
						tnmi.flush()
					tnmi.write('{}\t{}\n'.format(nmi, job.params['jobsuff']))


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args
			, timeout=timeout, ondone=aggLevs, params={'taskoutp': taskoutp, 'jobsuff': jobsuff}
			, stdout=PIPE, stderr=logsbase + _EXTERR))


	def nmisEvaluate(jobs, cfile, jobname, task, taskoutp, rcpoutp, jobsuff, logsbase):
		"""Add nmi evaluatoin job to the current jobs

		jobs  - list of jobs
		cfile  - clusters file to be evaluated
		jobname  - name of the creating job
		task  - task to wich the job belongs
		taskoutp  - accumulative output file for all jobs of the current task
		rcpoutp  - file name for the aggregated output of the jobs resources consumption
		jobsuff  - job specific suffix after the mutual name base inherent to the task
		logsbase  - base part of the file name for the logs including errors
		"""
		# Processing is performed from the algorithms dir
		args = ('../exectime', '-o=../' + rcpoutp, '-n=' + jobname, './onmi_sum', '../' + basefile, '../' + cfile)

		# Job postprocessing
		def aggLevs(job):
			"""Aggregate results over all levels, appending final value for each level to the dedicated file"""
			try:
				result = job.proc.communicate()[0]
				nmi = float(result)  # Read buffered stdout
			except ValueError:
				print('ERROR, nmi_s evaluation failed for the job "{}": {}'
					.format(job.name, result), file=sys.stderr)
			else:
				taskoutp = job.params['taskoutp']
				with open(taskoutp, 'a') as tnmi:  # Append to the end
					if not os.path.getsize(taskoutp):
						tnmi.write('# NMI_S\t[shuffle_]level\n')
						tnmi.flush()
					tnmi.write('{}\t{}\n'.format(nmi, job.params['jobsuff']))


		jobs.append(Job(name=jobname, task=task, workdir=_ALGSDIR, args=args
			, timeout=timeout, ondone=aggLevs, params={'taskoutp': taskoutp, 'jobsuff': jobsuff}
			, stdout=PIPE, stderr=logsbase + _EXTERR))



	def modAggregate(task):
		"""Aggregate resutls for the executed task from task-related resulting files
		"""
		# Traverse over *.mod files, evaluate mean and 2*STD for shuffles and output
		# everything to the accumulative average file: measdir/scp.mod
		pass
		## Sort the task acc mod file and accumulate the largest value to the totall acc mod file
		## Note: here full path is required
		#amodname = ''.join((_RESDIR, algname, _extmod))  # Name of the file with resulting modularities
		#if not os.path.exists(amodname):
		#	with open(amodname, 'a') as amod:
		#		if not os.path.getsize(amodname):
		#			amod.write('# Network\tQ\tTask\n')  # Network\tQ\tQ_STD
		#			amod.flush()
		#with open(amodname, 'a') as amod:  # Append to the end
		#	subprocess.call(''.join(('printf "', task, '\t `sort -g -r "', taskoutp,'" | head -n 1`\n"')), stdout=amod, shell=True)
		#assert task.params, 'Task parameres must represent data structere to hold aggregated results'
		#processRaw(task.params, )
		pass



	def nmixAggregate(task):
		pass


	if measure == 'mod':
		evalGeneric(execpool, measure, algname, basefile, _MODDIR, timeout, modEvaluate, modAggregate, pathid)
	elif measure == 'nmi':
		evalGeneric(execpool, measure, algname, basefile, _NMIDIR, timeout, nmiEvaluate, nmixAggregate, pathid)
	elif measure == 'nmi_s':
		evalGeneric(execpool, measure, algname, basefile, _NMIDIR, timeout, nmisEvaluate, nmixAggregate, pathid, tidy=False)
	else:
		raise ValueError('Unexpected measure: ' + measure)


# ATTENTION: this function should not be defined to not beight automatically executed
#def execAlgorithm(execpool, netfile, asym, timeout, pathid='', selfexec=False, **kwargs):
#	"""Execute the algorithm (stub)
#
#	execpool  - execution pool to perform execution of current task
#	netfile  -  input network to be processed
#	asym  - network links weights are assymetric (in/outbound weights can be different)
#	timeout  - execution timeout for this task
#	pathid  - path id of the net to distinguish nets with the same name located in different dirs.
#		Note: pathid already pretended with the separator symbol
#	selfexec=False  - current execution is the external or internal self call
#	kwargs  - optional algorithm-specific keyword agguments
#
#	return  - number of executions
#	"""
#	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
#		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
#		.format(execpool, netfile, asym, timeout))
#	return 0


# Louvain
## Original Louvain
#def execLouvain(execpool, netfile, asym, timeout, pathid='', tasknum=0):
#	"""Execute Louvain
#	Results are not stable => multiple execution is desirable.
#
#	tasknum  - index of the execution on the same dataset
#	"""
#	# Fetch the task name and chose correct network filename
#	netfile = os.path.splitext(netfile)[0]  # Remove the extension
#	task = os.path.split(netfile)[1]  # Base name of the network
#	assert task, 'The network name should exists'
#	if tasknum:
#		task = '-'.join((task, str(tasknum)))
#	netfile = '../' + netfile  # Use network in the required format
#
#	algname = 'louvain'
#	# ./community graph.bin -l -1 -w graph.weights > graph.tree
#	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
#		, './community', netfile + '.lig', '-l', '-1', '-v', '-w', netfile + '.liw')
#	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args
#		, timeout=timeout, stdout=''.join((_RESDIR, algname, '/', task, '.loc'))
#		, stderr=''.join((_RESDIR, algname, '/', task, _EXTLOG))))
#	return 1
#
#
#def evalLouvain(execpool, basefile, measure, timeout):
#	return


def execLouvain_ig(execpool, netfile, asym, timeout, pathid='', selfexec=False):
	"""Execute Louvain
	Results are not stable => multiple execution is desirable.

	returns number of executions or None
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	#if tasknum:
	#	task = '_'.join((task, str(tasknum)))

	algname = 'louvain_igraph'
	# ./louvain_igraph.py -i=../syntnets/1K5.nsa -ol=louvain_igoutp/1K5/1K5.cnl
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	## Louvain accumulated statistics over shuffled modification of the network or total statistics for all networks
	#extres = '.acs'
	#if not selfexec:
	#	outpdir = ''.join((_RESDIR, algname, '/'))
	#	if not os.path.exists(outpdir):
	#		os.makedirs(outpdir)
	#	# Just erase the file of the accum results
	#	with open(taskpath + extres, 'w') as accres:
	#		accres.write('# Accumulated results for the shuffles\n')
	#
	#def postexec(job):
	#	"""Copy final modularity output to the separate file"""
	#	# File name of the accumulated result
	#	# Note: here full path is required
	#	accname = ''.join((_ALGSDIR, _RESDIR, algname, extres))
	#	with open(accname, 'a') as accres:  # Append to the end
	#		# TODO: Evaluate the average
	#		subprocess.call(('tail', '-n 1', taskpath + _EXTLOG), stdout=accres)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		# Note: igraph-python is a Cython wrapper around C igraph lib. Calls are much faster on CPython than on PyPy
		, 'python', ''.join(('./', algname, '.py')), ''.join(('-i=../', netfile, netext))
		, ''.join(('-ol=../', taskpath, _EXTCLNODES)))
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args, timeout=timeout
		#, ondone=postexec
		, stdout=os.devnull, stderr=''.join((taskpath, _EXTLOG))))

	execnum = 1
	# Note: execution on shuffled network instances is now generalized for all algorithms
	## Run again for all shuffled nets
	#if not selfexec:
	#	selfexec = True
	#	netdir = os.path.split(netfile)[0] + '/'
	#	#print('Netdir: ', netdir)
	#	for netfile in glob.iglob(''.join((escapePathWildcards(netdir), escapePathWildcards(task), '/*', netext))):
	#		execLouvain_ig(execpool, netfile, asym, timeout, selfexec)
	#		execnum += 1
	return execnum
#
#
#def evalLouvain_ig(execpool, cnlfile, timeout):
#	#print('Applying {} to {}'.format('louvain_igraph', cnlfile))
#	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph')
#
#
#def evalLouvain_igNS(execpool, basefile, measure, timeout):
#	"""Evaluate Louvain_igraph by NMI_sum (onmi) instead of NMI_conv(gecmi)"""
#	evalAlgorithm(execpool, cnlfile, timeout, 'louvain_igraph', evalbin='./onmi_sum', evalname='nmi_s')
#
#
#def modLouvain_ig(execpool, netfile, timeout):
#	modAlgorithm(execpool, netfile, timeout, 'louvain_igraph')


# SCP (Sequential algorithm for fast clique percolation)
def execScp(execpool, netfile, asym, timeout, pathid=''):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task, netext = os.path.splitext(netfile)
	task = os.path.split(task)[1]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'scp'
	kmin = 3  # Min clique size to be used for the communities identificaiton
	kmax = 8  # Max clique size (~ min node degree to be considered)
	# Run for range of clique sizes
	for k in range(kmin, kmax + 1):
		kstr = str(k)
		kstrex = 'k' + kstr
		# Embed params into the task name
		taskbasex, taskshuf = os.path.splitext(task)
		ktask = ''.join((taskbasex, _SEPPARS, kstrex, taskshuf))
		# Backup previous results if exist
		taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, ktask, pathid))

		preparePath(taskpath)

		# ATTENTION: a single argument is k-clique size, specified later
		steps = '10'  # Use 10 levels in the hierarchy Ganxis
		resbase = ''.join(('../', taskpath, '/', ktask))  # Base name of the result
		# scp.py netname k [start_linksnum end__linksnum numberofevaluations] [weight]
		args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', ktask, pathid))
			, PYEXEC, ''.join(('./', algname, '.py')), '../' + netfile, kstr, steps, resbase + _EXTCLNODES)

		def tidy(job):
			"""Remove empty resulting folders"""
			# Note: GANXiS leaves empty ./output dir in the _ALGSDIR, which should be deleted
			path = os.path.split(job.args[-1])[0][3:]  # Skip '../' prefix
			if dirempty(path):
				os.rmdir(path)

		#print('> Starting job {} with args: {}'.format('_'.join((ktask, algname, kstrex)), args + [kstr]))
		execpool.execute(Job(name='_'.join((ktask, algname)), workdir=_ALGSDIR, args=args, timeout=timeout
			, ondone=tidy, stderr=taskpath + _EXTLOG))

	return kmax + 1 - kmin


def execRandcommuns(execpool, netfile, asym, timeout, pathid='', instances=5):  # _netshuffles + 1
	"""Execute Randcommuns, Random Disjoint Clustering
	Results are not stable => multiple execution is desirable.

	instances  - number of networks instances to be generated
	"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile, netext = os.path.splitext(netfile)  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	algname = 'randcommuns'
	# Backup previous results if exist
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	# ./randcommuns.py -g=../syntnets/1K5.cnl -i=../syntnets/1K5.nsa -n=10
	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, PYEXEC, ''.join(('./', algname, '.py')), ''.join(('-g=../', netfile, _EXTCLNODES))
		, ''.join(('-i=../', netfile, netext)), ''.join(('-o=../', taskpath))
		, ''.join(('-n=', str(instances))))
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args, timeout=timeout
		, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecs(execpool, netfile, asym, timeout, pathid=''):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecs'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cls=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsOtl(execpool, netfile, asym, timeout, pathid=''):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecsotl'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-cols=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsAhOtl(execpool, netfile, asym, timeout, pathid=''):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecsahotl'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', ''.join(('-coas=../', taskpath, '/', task, '_', algname, _EXTCLNODES))
		, '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=os.devnull, stderr=taskpath + _EXTLOG))
	return 1


def execHirecsNounwrap(execpool, netfile, asym, timeout, pathid=''):
	"""Hirecs which performs the clustering, but does not unwrappes the hierarchy into levels,
	just outputs the folded hierarchy"""
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name and chose correct network filename
	netfile = os.path.splitext(netfile)[0]  # Remove the extension
	task = os.path.split(netfile)[1]  # Base name of the network
	assert task, 'The network name should exists'
	netfile += '.hig'  # Use network in the required format
	algname = 'hirecshfold'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))

	preparePath(taskpath)

	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './hirecs', '-oc', '../' + netfile)
	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args
		, timeout=timeout, stdout=''.join((taskpath, '.hoc'))
		, stderr=taskpath + _EXTLOG))
	return 1


# Oslom2
def execOslom2(execpool, netfile, asym, timeout, pathid=''):
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.split(netfile)[1]  # Base name of the network
	task, netext = os.path.splitext(task)
	assert task, 'The network name should exists'

	algname = 'oslom2'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))
	# Note: wighted networks (-w) stands for the used null model, not for the input file format.
	# Link weight is set to 1 if not specified in the file for weighted network.
	args = ('../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, './oslom_undir' if not asym else './oslom_dir', '-f', '../' + netfile, '-w')

	preparePath(taskpath)

	netdir = os.path.split(netfile)[0] + '/'
	# Copy results to the required dir on postprocessing
	def postexec(job):
		# Copy communities output from original location to the target one
		origResDir = ''.join((netdir, task, netext, '_oslo_files/'))
		for fname in glob.iglob(escapePathWildcards(origResDir) +'tp*'):
			shutil.copy2(fname, taskpath)

		# Move whole dir as extra task output to the logsdir
		outpdire = taskpath + '/extra/'
		if not os.path.exists(outpdire):
			os.mkdir(outpdire)
		else:
			# If dest dir already exists, remove it to avoid exception on rename
			shutil.rmtree(outpdire)
		os.rename(origResDir, outpdire)

		# Note: oslom2 leaves ./tp file in the _ALGSDIR, which should be deleted
		fname = _ALGSDIR + 'tp'
		if os.path.exists(fname):
			os.remove(fname)

	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=postexec
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1


# Ganxis (SLPA)
def execGanxis(execpool, netfile, asym, timeout, pathid=''):
	#print('> exec params:\n\texecpool: {}\n\tnetfile: {}\n\tasym: {}\n\ttimeout: {}'
	#	.format(execpool, netfile, asym, timeout))
	assert execpool and netfile and (asym is None or isinstance(asym, bool)) and timeout + 0 >= 0, (
		'Invalid input parameters:\n\texecpool: {},\n\tnet: {},\n\tasym: {},\n\ttimeout: {}'
		.format(execpool, netfile, asym, timeout))
	# Fetch the task name
	task = os.path.splitext(os.path.split(netfile)[1])[0]  # Base name of the network
	assert task, 'The network name should exists'

	algname = 'ganxis'
	taskpath = ''.join((_RESDIR, algname, '/', _CLSDIR, task, pathid))
	args = ['../exectime', ''.join(('-o=../', _RESDIR, algname, _EXTEXECTIME)), ''.join(('-n=', task, pathid)), '-s=/etime_' + algname
		, 'java', '-jar', './GANXiSw.jar', '-i', '../' + netfile, '-d', '../' + taskpath]
	if not asym:
		args.append('-Sym 1')  # Check existance of the back links and generate them if requried

	preparePath(taskpath)

	def tidy(job):
		# Note: GANXiS leaves empty ./output dir in the _ALGSDIR, which should be deleted
		tmp = _ALGSDIR + 'output/'
		if os.path.exists(tmp):
			#os.rmdir(tmp)
			shutil.rmtree(tmp)

	execpool.execute(Job(name='_'.join((task, algname)), workdir=_ALGSDIR, args=args, timeout=timeout, ondone=tidy
		, stdout=taskpath + _EXTLOG, stderr=taskpath + _EXTERR))
	return 1
