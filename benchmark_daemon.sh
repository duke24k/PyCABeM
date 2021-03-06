#!/bin/sh
#
# \description  Generate synthetic networks with shuffles and execute
# benchmarking for all algorithms on these networks.
#
# \author Artem V L <luart@ya.ru>  http://exascale.info, http://lumais.com

PYTHON=`whereis pypy | grep "/"`
echo PYTHON1: $PYTHON
if [ "$PYTHON" ]
then
	PYTHON="pypy"
else 
	PYTHON="python"
fi

TIMEOUT=6  # 6 hours per singe execution of any algorithm on any network
TIMEOUT_UNIT=h
#DATASETS=syntnets
EXECLOG=bench.log  # Log for the execution status
EXECERR=bench.err  # Log for execution errors

echo 'Starting the benchmark in daemom mode ...'
#  -dw=${DATASETS}
nohup $PYTHON benchmark.py -g=4.4 -cr -r -e -t$TIMEOUT_UNIT=$TIMEOUT 1> ${EXECLOG} 2> ${EXECERR} &
