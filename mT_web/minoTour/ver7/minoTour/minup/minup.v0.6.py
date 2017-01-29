#!/usr/bin/env python
import sys, os, re
import time
import datetime
import logging
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler
import threading, thread
import h5py
from Bio import SeqIO
from StringIO import StringIO
import MySQLdb
import subprocess
import string
import configargparse
from warnings import filterwarnings
import socket
import hashlib
import xmltodict
import numpy

## minup: a program to process & upload MinION fast5 files in to the minoTour website in real-time or post-run.
## written & designed by Martin J. Blythe, Fei Sang & Matt W. Loose. DeepSeq, The University of Nottingham 2014. UK
global minup_version
minup_version="0.6"

global oper
oper="linux"
#oper="windows"

global config_file
global logfolder
global valid_ref_dir
global bwa_index_dir
global last_index_dir

## linux version
if (oper is "linux"):
    config_file = os.path.join(os.path.sep, os.path.dirname(os.path.realpath('__file__')), 'minup_posix.config')
    logfolder=os.path.join(os.path.sep, os.path.dirname(os.path.realpath('__file__')),"minup_run_logs" )
    valid_ref_dir=os.path.join(os.path.sep, os.path.dirname(os.path.realpath('__file__')),"valid_reference_fasta_files" )
    bwa_index_dir=os.path.join(os.path.sep, os.path.dirname(os.path.realpath('__file__')),"bwa_indexes" )
    last_index_dir=os.path.join(os.path.sep, os.path.dirname(os.path.realpath('__file__')),"last_indexes" )

## windows version
if (oper is "windows"):
    config_file = os.path.join(os.path.sep,sys.prefix,'minup_windows.config')
    logfolder=os.path.join(os.path.sep,sys.prefix,"minup_run_logs")
    valid_ref_dir=os.path.join(os.path.sep,sys.prefix,"valid_reference_fasta_files")
    bwa_index_dir=os.path.join(os.path.sep,sys.prefix,"bwa_indexes")
    last_index_dir=os.path.join(os.path.sep,sys.prefix,"last_indexes")

if not os.path.exists(logfolder):
    os.makedirs(logfolder)
if not os.path.exists(valid_ref_dir):
    os.makedirs(valid_ref_dir)
if not os.path.exists(bwa_index_dir):
    os.makedirs(bwa_index_dir)
if not os.path.exists(last_index_dir):
    os.makedirs(last_index_dir)

parser = configargparse.ArgParser(description='minup: A program to analyse minION fast5 files in real-time or post-run.', default_config_files=[config_file])
parser.add('-dbh', '--mysql-host', type=str, dest='dbhost', required=False, default='localhost', help="The location of the MySQL database. default is 'localhost'.")
parser.add('-dbu', '--mysql-username', type=str, dest='dbusername', required=True, default=None,  help="The MySQL username with create & write privileges on MinoTour.")
parser.add('-dbp', '--mysql-port', type=int, dest='dbport', required=False, default=3306,  help="The MySQL port number, else the default port '3306' is used.")
parser.add('-pw', '--mysql-password', type=str, dest='dbpass', required=True, default=None,  help="The password for the MySQL username with permission to upload to MinoTour.")
parser.add('-f', '--align-ref-fasta', type=str, required=False, default=False, help="The reference fasta file to align reads against. Using this option enables read alignment provided LastAl and LastDB are in the path. Leaving this entry blank will upload the data without any alignment. To use multiple reference fasta files input them as one text string seperated by commas (no white spaces) ", dest='ref_fasta')
parser.add('-b', '--align-batch-fasta', action='store_true', required=False, default=False, help="Align reads in batch processing mode. Assumes the watch-dir (-w) is pointed at a directory with one or more \"downloads\" folders below it somewhere. Each \"downloads\" folder can have a subfolder named \"reference\" containing the fasta file(s) to align the fast5 reads in the corresponding \"downloads\" folder to ", dest='batch_fasta')
parser.add('-w', '--watch-dir', type=str, required=True, default=None, help="The path to the folder containing the downloads directory with fast5 reads to analyse - e.g. C:\data\minion\downloads (for windows).", dest='watchdir')
#parser.add('-n', '--aligning-threads', type=str, required=False, help="The number of threads to use for aligning", default=3, dest='threads')
parser.add('-u', '--minotour-username', type=str, required=True, help="The MinoTour username with permissions to upload data.", default=False, dest='minotourusername')
parser.add('-s', '--minotour-sharing-usernames', type=str, required=False, default=False, help="A comma seperated list (with no whitespaces) of other MinoTour users who will also be able to view the data.", dest='view_users')
parser.add('-o', '--flowcell-owner', type=str, required=False, default="minionowner", help="The name of the minion owner. 'minionowner' is the default", dest='flowcell_owner')
parser.add('-r', '--run-number', type=str, required=False, default=0, help="The run number of the flowcell. The default value is 0. ", dest='run_num')
parser.add('-c', '--commment-true', action='store_true', help="Add a comment to the comments field for this run. Follow the prompt once minup starts . ", default=False, dest='add_comment')
parser.add('-last', '--last-align-true',action='store_true', help="align reads with LAST", default=False, dest='last_align')
parser.add('-bwa',  '--bwa-align-true',action='store_true', help="align reads with BWA", default=False, dest='bwa_align')
parser.add('-bwa-opts', '--bwa-align-options',type=str,  required=False, help="BWA options: Enter a comma-seperated list of BWA options without spaces or '-' characters e.g. k12,T0", default="T0", dest='bwa_options')
parser.add('-last-opts', '--last-align-options',type=str, required=False, help="LAST options: Enter a comma-seperated list of LAST options without spaces or '-' characters e.g. s2,T0,Q0,a1", default="s2,T0,Q0,a1", dest='last_options')
parser.add('-pin', '--security-pin', type=str, required=False, default=False, help="pin number for remote control", dest='pin')
parser.add('-ip', '--ip-address', type=str, required=False, default=False, help="Used for remote control with option '-pin'. Provide IP address of the computer running minKNOW. The default is the IP address of this computer", dest='ip_address')
parser.add('-t', '--insert-tel-true', action='store_true', help="Store all the telemetry data from the read files online. This feature is currently in development.", default=False,dest='telem')
parser.add('-d', '--drop-db-true', action='store_true', help="Drop existing database if it already exists.", default=False, dest='drop_db')
parser.add('-v', '--verbose-true', action='store_true', help="Print detailed messages while processing files.", default=False, dest='verbose')
parser.add('-name', '--name-custom', type=str, required=False, default="", help="Provide a modifier to the database name. This allows you to upload the same dataset to minoTour more than once. The additional string should be as short as possible.", dest='custom_name')
parser.add('-cs', '--commment-string', nargs='+', type=str, dest='added_comment', help="Add given string to the comments field for this run", default='', ) # MS
parser.add('-res', '--resume-upload', action='store_true', help="Add files to a partially uploaded database", default=False, dest='resume')
parser.add('-ver', '--version', action='store_true', help="Report the current version of minUP.", default=False, dest='version') # ML
args = parser.parse_args()

global dbcheckhash
dbcheckhash=dict()
dbcheckhash["dbname"]=dict()
dbcheckhash["barcoded"]=dict()
dbcheckhash["barcode_info"]=dict()
dbcheckhash["runindex"]=dict()
dbcheckhash["modelcheck"]=dict()
dbcheckhash["logfile"]=dict()
#dbcheckhash["mafoutdict"]=dict()
#dbcheckhash["samoutdict"]=dict()

global ref_fasta_hash
ref_fasta_hash=dict()

global dbname
dbname=str()

global comments
comments=dict()

global connection_pool
connection_pool=dict()

#####################################################################

def check_read(filepath, hdf, cursor):
    filename = os.path.basename(filepath)
    if (args.verbose is True):
        print time.strftime('%Y-%m-%d %H:%M:%S'), "processing:", filename
    parts = filename.split("_")
    str = "_";
    dbname=str.join(parts[0:(len(parts)-5)])
    dbname = re.sub('[.!,; ]', '', dbname)
    if (len(args.custom_name) > 0):
        dbname = args.minotourusername + "_" + args.custom_name + "_" + dbname
    else:
        dbname = args.minotourusername + "_" + dbname
    if (len(dbname) > 64):
        dbname = dbname[:64]
    ######
    global runindex
    ##########################################################################
    if (dbname in dbcheckhash["dbname"]): # so data from this run has been seen before in this instance of minup so switch to it!
        if (dbcheckhash["dbname"][dbname] is False):
            if (args.verbose is True):
                print "switching to database: ", dbname
            sql="USE %s" % (dbname)
            cursor.execute(sql)
            ############################
            runindex =dbcheckhash["runindex"][dbname]
            comment_string = "minUp switched runname"
            start_time=time.strftime('%Y-%m-%d %H:%M:%S')
            sql="INSERT INTO Gru.comments (runindex,runname,user_name,comment,name,date) VALUES (%s,'%s','%s','%s','%s','%s')" %(runindex,dbname,args.minotourusername,comment_string,args.minotourusername,start_time)
            #print sql
            db.escape_string(sql)
            cursor.execute(sql)
            db.commit()
            #############################
            for e in dbcheckhash["dbname"].keys():
                dbcheckhash["dbname"][e] = False
            dbcheckhash["dbname"][dbname] = True
    ###########################################################################
    if (dbname not in dbcheckhash["dbname"]): ## so the db has not been seen before.. time to set up lots of things...
        dbcheckhash["barcoded"][dbname]=False
        dbcheckhash["barcode_info"][dbname]=False
        dbcheckhash["logfile"][dbname]=os.path.join(os.path.sep,logfolder,dbname+".minup.log")
        if (args.verbose is True):
            print "trying database: ", dbname
        sql = "SHOW DATABASES LIKE \'%s\'" % (dbname)
        #print sql
        cursor.execute(sql)
        if (cursor.fetchone()):
            if (args.verbose is True):
                print "database exists!"

            ## drop the existing database, if selected
            if (args.drop_db is True):
                sql = "DROP DATABASE %s" % (dbname)
                #print sql
                cursor.execute(sql)
                db.commit()
                if (args.verbose is True):
                    print "database dropped."
            else:
                print >>sys.stderr, "%s run database already exists. To write over the data re-run the minUP command with option -d" % (dbname)
                sys.exit()

        if (args.drop_db is True):
            print "deleting exisiting run from Gru now."
            sql = "DELETE FROM Gru.userrun WHERE runindex IN (SELECT runindex FROM Gru.minIONruns WHERE runname = \"%s\")" % (dbname)
            #print sql
            cursor.execute(sql)
            db.commit()
            sql = "DELETE FROM Gru.minIONruns WHERE runname = \'%s\'" % (dbname)
            #print sql
            cursor.execute(sql)
            db.commit()

        ################# mincontrol ####################
        ## get the IP address of the host
        ip="127.0.0.1"
        try:
            ip=socket.gethostbyname(socket.gethostname())
        except Exception, err:
            err_string = "Error obtaining upload IP adress"
            print >>sys.stderr, err_string

        #################################################
        #### This bit adds columns to Gru.minIONruns ####
        modify_gru(cursor)
        #################################################

        #### Create a new empty database
        if (args.verbose is True):
            print "making new database: ", dbname

        sql="CREATE DATABASE %s" % (dbname)
        cursor.execute(sql)
        sql="USE %s" % (dbname)
        cursor.execute(sql)
        create_general_table('config_general',cursor) # make a table
        create_trackingid_table('tracking_id',cursor) # make another table
        create_basecall_summary_info('basecall_summary',cursor) # make another table!
        create_events_model_fastq_table('basecalled_template', cursor) # make another table
        create_events_model_fastq_table('basecalled_complement', cursor) # make another table
        create_basecalled2d_fastq_table('basecalled_2d', cursor) # make another table
        ########################################
        if (args.telem is True):
            for i in xrange(0,10):
                temptable = 'caller_basecalled_template_%d' % (i)
                comptable = 'caller_basecalled_complement_%d' % (i)
                twod_aligntable = 'caller_basecalled_2d_alignment_%d' % (i)
                create_caller_table_noindex(temptable, cursor)
                create_caller_table_noindex(comptable, cursor)
                create_2d_alignment_table(twod_aligntable, cursor)
            create_model_list_table("model_list", cursor)
            create_model_data_table("model_data", cursor)

        ########################################
        ######## Assign the correct reference fasta for this dbname if applicable
        if (args.batch_fasta is not False):
            for refbasename in ref_fasta_hash.keys():
                common_path= os.path.commonprefix((ref_fasta_hash[refbasename]['path'], filepath)).rstrip('\\|\/|re|\\re|\/re')
                if (common_path.endswith("downloads") ):
                    ref_fasta_hash[dbname]=ref_fasta_hash[refbasename]
                    #del ref_fasta_hash[refbasename]

        if (args.ref_fasta is not False):
            for refbasename in ref_fasta_hash.keys(): # there should only be one key
                ref_fasta_hash[dbname]=ref_fasta_hash[refbasename]

        ###########################################
        if (dbname in ref_fasta_hash): # great, we assigned the reference fasta to this dbname
            create_reference_table('reference_seq_info', cursor)
            create_5_3_prime_align_tables('last_align_basecalled_template', cursor)
            create_5_3_prime_align_tables('last_align_basecalled_complement', cursor)
            create_5_3_prime_align_tables('last_align_basecalled_2d', cursor)

            if (args.last_align is True):
                #create_align_table('last_align_basecalled_template', cursor)
                #create_align_table('last_align_basecalled_complement', cursor)
                #create_align_table('last_align_basecalled_2d', cursor)
                create_align_table_maf('last_align_maf_basecalled_template', cursor)
                create_align_table_maf('last_align_maf_basecalled_complement', cursor)
                create_align_table_maf('last_align_maf_basecalled_2d', cursor)

            if (args.bwa_align is True):
                create_align_table_sam('align_sam_basecalled_template', cursor)
                create_align_table_sam('align_sam_basecalled_complement', cursor)
                create_align_table_sam('align_sam_basecalled_2d', cursor)

            #dbcheckhash["mafoutdict"][dbname]=open(dbname+"."+process+".align.maf","w")
            if (args.telem is True):
                create_ref_kmer_table('ref_sequence_kmer', cursor)

            for refname in ref_fasta_hash[dbname]["seq_len"].iterkeys():
                #print "refname", refname
                reference=ref_fasta_hash[dbname]["seq_file"][refname]
                reflen=ref_fasta_hash[dbname]["seq_len"][refname]
                reflength=ref_fasta_hash[dbname]["seq_file_len"][reference]
                refid=mysql_load_from_hashes(cursor, 'reference_seq_info', {'refname':refname, 'reflen':reflen, 'reffile':reference, 'ref_total_len':reflength})
                ref_fasta_hash[dbname]["refid"][refname]=refid
                if (args.telem is True):
                    kmers=ref_fasta_hash[dbname]["kmer"][refname]
                    load_ref_kmer_hash('ref_sequence_kmer', kmers, refid, cursor)

        ###############################################
        ######## See if theres any ENA XML stuff to add. Need to do this now as it changes the "comment" in Gru.minionRuns entry
        #print "C", comment
        ena_flowcell_owner=None
        for xml_to_downloads_path in xml_file_dict.keys():
            #xmlpath=xml_file_dict["study"][study_id]["path"]
            common_path= os.path.commonprefix((xml_to_downloads_path, filepath)).rstrip('\\|\/|re')
            if (common_path.endswith("downloads") ):
                print "found XML data for:", dbname
                create_xml_table("XML", cursor)
                ###############################
                for study_id in xml_file_dict[xml_to_downloads_path]["study"].keys():
                    ena_flowcell_owner=study_id
                    study_xml=xml_file_dict[xml_to_downloads_path]["study"][study_id]["xml"]
                    study_file=xml_file_dict[xml_to_downloads_path]["study"][study_id]["file"]
                    study_title=xml_file_dict[xml_to_downloads_path]["study"][study_id]["title"]
                    study_abstract=xml_file_dict[xml_to_downloads_path]["study"][study_id]["abstract"]
                    exp_c="NA"
                    samp_c="NA"
                    run_c="NA"
                    mysql_load_from_hashes(cursor, "XML", {'type':'study','primary_id':study_id,'filename':study_file,'xml':study_xml })
                    for exp_id in xml_file_dict[xml_to_downloads_path]["experiment"].keys():
                        if (study_id == xml_file_dict[xml_to_downloads_path]["experiment"][exp_id]["study_id"]):
                            exp_c=exp_id
                            exp_xml=xml_file_dict[xml_to_downloads_path]["experiment"][exp_id]["xml"]
                            exp_file=xml_file_dict[xml_to_downloads_path]["experiment"][exp_id]["file"]
                            sample_id=xml_file_dict[xml_to_downloads_path]["experiment"][exp_id]["sample_id"]
                            mysql_load_from_hashes(cursor, "XML", {'type':'experiment','primary_id':exp_id,'filename':exp_file,'xml':exp_xml })

                            if (sample_id in xml_file_dict[xml_to_downloads_path]["sample"]):
                                samp_c=sample_id
                                sample_xml=xml_file_dict[xml_to_downloads_path]["sample"][sample_id]["xml"]
                                sample_file=xml_file_dict[xml_to_downloads_path]["sample"][sample_id]["file"]
                                mysql_load_from_hashes(cursor, "XML", {'type':'sample','primary_id':sample_id,'filename':sample_file,'xml':sample_xml })

                            for run_id in xml_file_dict[xml_to_downloads_path]["run"].keys():
                                if (exp_id == xml_file_dict[xml_to_downloads_path]["run"][run_id]["exp_id"]):
                                    run_c=run_id
                                    run_xml=xml_file_dict[xml_to_downloads_path]["run"][run_id]["xml"]
                                    run_file=xml_file_dict[xml_to_downloads_path]["run"][run_id]["file"]
                                    mysql_load_from_hashes(cursor, "XML", {'type':'run','primary_id':run_id,'filename':run_file,'xml':run_xml})
                    comments[dbname]="ENA data. Study:%s Title: %s Abstract: %s Experiment:%s Sample:%s Run:%s" % (study_id,study_title,study_abstract,exp_c,samp_c,run_c)

        #################################################
        ########## Make entries in the Gru database
        # try and get the right basecall-configuration general
        basecalltype="Basecall_1D_CDNA"
        basecalltype2="Basecall_2D"
        basecalldir=''
        basecalldirconfig=''
        for x in range (0,9):
            string='/Analyses/%s_00%s/Configuration/general' % (basecalltype, x)
            if (string in hdf):
                basecalldir='/Analyses/%s_00%s/' % (basecalltype,x)
                basecalldirconfig=string
                break
            string='/Analyses/%s_00%s/Configuration/general' % (basecalltype2, x)
            if (string in hdf):
                basecalldir='/Analyses/%s_00%s/' % (basecalltype2,x)
                basecalldirconfig=string
                break

        #print "basecalldirconfig", basecalldirconfig
        ## get some data out of tacking_id and general
        configdata=hdf[basecalldirconfig]
        trackingid=hdf['/UniqueGlobalKey/tracking_id']
        metrichor_info=hdf[basecalldir]
        expstarttimecode=datetime.datetime.fromtimestamp(int(trackingid.attrs['exp_start_time'])).strftime('%Y-%m-%d')
        flowcellid = trackingid.attrs['device_id']
        version = metrichor_info.attrs['version']
        basecalleralg = configdata.attrs['workflow_name']

        runnumber= args.run_num
        flowcellowner = 'NULL'
        username =args.minotourusername
        if (args.flowcell_owner is not None):
            flowcellowner=args.flowcell_owner
        if (ena_flowcell_owner is not None):
            flowcellowner=ena_flowcell_owner

        ## get info on the reference sequence, if used
        big_reference = 'NOREFERENCE'
        big_reflength = '0'
        if (dbname in ref_fasta_hash): # so there's some reference data for this dbname
            big_reference = ref_fasta_hash[dbname]["big_name"]
            big_reflength = ref_fasta_hash[dbname]["big_len"]

        ## make entries into Gru for this new database
        comment = comments['default']
        if dbname in comments:
            comment = comments[dbname]

        process="noalign"
        if (args.last_align is True):
            process="LAST"
        if (args.bwa_align is True):
            process="BWA"

        wdir = args.watchdir
        if wdir.endswith('\\'): # remove trailing slash for windows.
            wdir = wdir[:-1]
        sql = "INSERT INTO Gru.minIONruns (date,user_name,flowcellid,runname,activeflag,comment,FlowCellOwner,RunNumber,reference,reflength,basecalleralg,version,minup_version,process,mt_ctrl_flag,watch_dir,host_ip) VALUES ('%s','%s','%s','%s',%s,'%s','%s',%s,'%s',%s,'%s','%s','%s','%s',%s,'%s','%s')"  % (expstarttimecode,args.minotourusername,flowcellid,dbname,1,comment,flowcellowner,runnumber,big_reference,big_reflength,basecalleralg,version,minup_version,process,1,wdir,ip)
        #print sql
        db.escape_string(sql)
        cursor.execute(sql)
        db.commit()
        runindex = cursor.lastrowid
        dbcheckhash["runindex"][dbname]=runindex
        #print "Runindex:",runindex

        ## add user names to Gru.userrun
        if (args.verbose is True):
            "adding users."
        view_users=[username]
        if (args.view_users):
            extra_names=args.view_users.split(',')
            view_users=view_users+extra_names

        for user_name in view_users:
            sql = "SELECT user_id FROM Gru.users WHERE user_name =\'%s\'" % (user_name)
            #print sql
            cursor.execute(sql)
            if (0< (cursor.rowcount) ):
                sql = "INSERT INTO Gru.userrun (user_id, runindex) VALUES ((SELECT user_id FROM Gru.users WHERE user_name =\'%s\') , (SELECT runindex FROM Gru.minIONruns WHERE runname = \"%s\") )" % (user_name, dbname)
                #print sql
                cursor.execute(sql)
                db.commit()
            else:
                print "The MinoTour username \"%s\" does not exist. Please create it or remove it from the input arguments" % (user_name)
                sys.exit()

        ## Create comment table if it doesn't exist
        create_comment_table_if_not_exists("Gru.comments", cursor)

        ## Add first comment to table
        start_time=time.strftime('%Y-%m-%d %H:%M:%S')
        comment_string = "minUp version %s started" % (minup_version)
        mysql_load_from_hashes(cursor, 'Gru.comments', {'runindex':runindex,'runname':dbname,'user_name':args.minotourusername,'comment':comment_string,'name':args.dbusername,'date':start_time})

        #####################################################
        ### make log file and initinal entry
        with open(dbcheckhash["logfile"][dbname],"w") as logfilehandle:
            logfilehandle.write("minup started at:\t%s%s" % (start_time,os.linesep) )
            logfilehandle.write("minup version:\t%s%s" % (minup_version,os.linesep) )
            logfilehandle.write("options:"+os.linesep)
            logfilehandle.write("minotour db host:\t%s%s" % (args.dbhost, os.linesep) )
            logfilehandle.write("minotour db user:\t%s%s" % (args.dbusername,os.linesep) )
            logfilehandle.write("minotour username:\t%s%s" % (args.minotourusername,os.linesep) )
            logfilehandle.write("minotour viewer usernames:\t%s%s"  % (view_users,os.linesep) )
            logfilehandle.write("flowcell owner:\t%s%s" % (flowcellowner,os.linesep) )
            logfilehandle.write("run number:\t%s%s" % (args.run_num,os.linesep) )
            logfilehandle.write("watch directory:\t%s%s" % (args.watchdir,os.linesep) )
            logfilehandle.write("upload telemetry:\t%s%s" % (args.telem,os.linesep) )
            logfilehandle.write("Reference Sequences:"+os.linesep)
            if (dbname in ref_fasta_hash):
                for refname in ref_fasta_hash[dbname]["seq_len"].iterkeys():
                    logfilehandle.write("Fasta:\t%s\tlength:\t%d%s" % (ref_fasta_hash[dbname]["seq_file"][refname], ref_fasta_hash[dbname]["seq_len"][refname], os.linesep) )
            else:
                logfilehandle.write("No reference sequence set"+os.linesep)

            logfilehandle.write("comment:\t%s%s"% (comment,os.linesep) )
            logfilehandle.write("Errors:"+os.linesep)
            logfilehandle.close()

        ################ mincontrol (remote control of minKNOW) ####################
        #parser.add('-dbh', '--mysql-host', type=str, dest='dbhost', required=False, default='localhost', help="The location of the MySQL database. default is 'localhost'.")
        #parser.add('-dbu', '--mysql-username', type=str, dest='dbusername', required=True, default=None,  help="The MySQL username with create & write privileges on MinoTour.")
        #parser.add('-dbp', '--mysql-port', type=int, dest='dbport', required=False, default=3306,  help="The MySQL port number, else the default port '3306' is used.")
        #parser.add('-pw', '--mysql-password', type=str, dest='dbpass', required=True, default=None,  help="The password for the MySQL username with permission to upload to MinoTour.")
        #parser.add('-db', '--db-name', type=str, dest='dbname', required=True, default=None,  help="The database being monitored.")
        #parser.add('-pin', '--security-pin', type=str, dest='pin',required=True, default=None, help="This is a security feature to prevent unauthorised remote control of a minION device. You need to provide a four digit pin number which must be entered on the website to remotely control the minION.")
        #parser.add('-ip', '--ip-address', type=str ,dest='ip',required=True,default=None, help="The IP address of the minKNOW machine.")
        if (args.pin is not False):
            if (args.verbose is True):
                print "starting mincontrol"
            control_ip=ip
            if (args.ip_address is not False):
                control_ip=args.ip_address

            #print "IP", control_ip
            # else the IP is the address of this machine
            create_mincontrol_interaction_table('interaction', cursor)
            create_mincontrol_messages_table('messages', cursor)
            create_mincontrol_barcode_control_table('barcode_control', cursor)

            try:
                if (oper is "linux"):
                    cmd='python mincontrol.py -dbh %s -dbu %s -dbp %d -pw %s -db %s -pin %s -ip %s' % (args.dbhost,args.dbusername,args.dbport,args.dbpass,dbname,args.pin,control_ip)
                    #print "CMD", cmd
                    subprocess.Popen(cmd, stdout=None, stderr=None, stdin=None ,shell=True)
                if (oper is "windows"):
                    cmd='mincontrol.exe -dbh %s -dbu %s -dbp %d -pw %s -db %s -pin %s -ip %s' % (args.dbhost,args.dbusername,args.dbport,args.dbpass,dbname,args.pin,control_ip)
                    #print "CMD", cmd
                    subprocess.Popen(cmd, stdout=None, stderr=None, stdin=None ,shell=True)#, creationflags=subprocess.CREATE_NEW_CONSOLE)
            except Exception, err:
                err_string = "Error starting mincontrol: %s " % (err)
                print >>sys.stderr, err_string
                with open(dbcheckhash["logfile"][dbname],"a") as logfilehandle:
                    logfilehandle.write(err_string+os.linesep)
                    logfilehandle.close()

        ##############################
        ## connection_pool for this db
        connection_pool[dbname]=list()
        if (args.last_align is True or args.bwa_align is True or args.telem is True):
            try:
                db_a = MySQLdb.connect(host=args.dbhost, user=args.dbusername, passwd=args.dbpass, port=args.dbport, db=dbname)
                connection_pool[dbname].append(db_a)
                db_b = MySQLdb.connect(host=args.dbhost, user=args.dbusername, passwd=args.dbpass, port=args.dbport, db=dbname)
                connection_pool[dbname].append(db_b)
                db_c = MySQLdb.connect(host=args.dbhost, user=args.dbusername, passwd=args.dbpass, port=args.dbport, db=dbname)
                connection_pool[dbname].append(db_c)

            except Exception, err:
                print >>sys.stderr, "Can't setup MySQL connection pool: %s" % (err)
                with open(dbcheckhash["logfile"][dbname],"a") as logfilehandle:
                    logfilehandle.write(err_string+os.linesep)
                    logfilehandle.close()
                sys.exit()


        #### this bit last to set the active database in this hash
        if dbcheckhash["dbname"]:
            for e in dbcheckhash["dbname"].keys():
                dbcheckhash["dbname"][e] = False
        dbcheckhash["dbname"][dbname] = True

    #################################
    # check if this is barcoded. Have to check with every read when: dbcheckhash["barcoded"][dbname]=False
    # if its a barcoded read.

    if (dbcheckhash["barcoded"][dbname] is False): # this will test the first read of this database to see if its a barcoded run
        barcoded=False
        for x in range(0,9):
            string='/Analyses/Barcoding_00%s' % (x)
            #print string
            if (string in hdf):
                barcoded=True
                barcode_align_obj=string+"/Barcoding/Aligns"
                break
        if (barcoded is True):
            create_barcode_table("barcode_assignment", cursor) # and create the table
            dbcheckhash["barcoded"][dbname]=True
            ###########

    if ( (dbcheckhash["barcode_info"][dbname] is False) and (args.pin is not False) ):
        barcode_align_obj=False
        for x in range(0,9):
            string='/Analyses/Barcoding_00%s/Barcoding/Aligns' % (x)
            if (string in hdf):
                barcode_align_obj=string
                break
        if (barcode_align_obj is not False):
            barcode_align_obj =hdf[barcode_align_obj][()]
            bcs=list()
            for i in range(len(barcode_align_obj)):
                if (barcode_align_obj[i].startswith(">") ):
                    bc=re.split(">| ", barcode_align_obj[i])[-1]
                    b="('%s',0)" % (bc)
                    bcs.append(b)
            sql="INSERT INTO barcode_control (barcodeid,complete) VALUES %s" % (','.join(bcs) )
            #print sql
            cursor.execute(sql)
            db.commit()
            dbcheckhash["barcode_info"][dbname]=True
    #####
    return dbname
    #####

#####################################################################

def process_fast5(filepath, hdf, dbname, cursor):

    checksum=hashlib.md5(open(filepath, 'rb').read()).hexdigest()
    #print checksum, type(checksum)
    ### find the right basecall_2D location, get configuaration genral data, and define the basename.
    basecalltype="Basecall_1D_CDNA"
    basecalltype2="Basecall_2D"
    basecalldir=''
    basecalldirconfig=''
    #print "REF", ref_fasta_hash

    for x in range (0,9):
        string='/Analyses/%s_00%s/Configuration/general' % (basecalltype,x)
        if (string in hdf):
            basecalldir='/Analyses/%s_00%s/' % (basecalltype,x)
            basecalldirconfig=string
            break
        string='/Analyses/%s_00%s/Configuration/general' % (basecalltype2,x)
        if (string in hdf):
            basecalldir='/Analyses/%s_00%s/' % (basecalltype2,x)
            basecalldirconfig=string
            break


    configdata=hdf[basecalldirconfig]
    basename=configdata.attrs['basename'] #= PLSP57501_17062014lambda_3216_1_ch101_file10_strand




    ## get all the tracking_id data, make primary entry for basename, and get basenameid
    tracking_id_fields=['basename','asic_id','asic_id_17','asic_id_eeprom','asic_temp','device_id','exp_script_purpose','exp_script_name','exp_start_time','flow_cell_id','heatsink_temp','hostname','run_id','version_name',]
    tracking_id_hash=make_hdf5_object_attr_hash(hdf['/UniqueGlobalKey/tracking_id'],tracking_id_fields)
    tracking_id_hash.update({'basename':basename,'file_path':filepath, 'md5sum':checksum})
    hdf5object=hdf['/UniqueGlobalKey/channel_id']
        #print "Got event location"
    for x in ('channel_number','digitisation','offset','sampling_rate'):
        if (x in hdf5object.attrs.keys() ):
            value=str(hdf5object.attrs[x])
            #print x, value
            tracking_id_hash.update({x:value})
    #range is a specifal case:
    #for x in ('range'):
    #    if (x in hdf5object.attrs.keys() ):
    #        value=str(hdf5object.attrs[x])
    #        print x, value
    #        tracking_id_hash.update({'range_val ':value})
    passcheck = 0
    if "/pass/" in filepath:
        passcheck = 1
    if "\\pass\\" in filepath:
        passcheck = 1
    tracking_id_hash.update({'pass':passcheck})
    basenameid=mysql_load_from_hashes(cursor,"tracking_id", tracking_id_hash)

    ## get all the data from Configuration/general, then add Event Detection mux pore number
    general_fields=['basename','local_folder','workflow_script','workflow_name','read_id','use_local','tag','model_path','complement_model','max_events','input','min_events','config','template_model','channel','metrichor_version','metrichor_time_stamp']
    general_hash=make_hdf5_object_attr_hash(configdata, general_fields)
    general_hash.update({'basename_id':basenameid})
    metrichor_info=hdf[basecalldir]
    general_hash.update({'metrichor_version':metrichor_info.attrs['version'], 'metrichor_time_stamp':metrichor_info.attrs['time_stamp']})

    ## get event detection for the read; define mux pore nuber
    eventdectionreadstring = '/Analyses/EventDetection_000/Reads/Read_%s' % (general_hash['read_id'])
    if (eventdectionreadstring in hdf):
        hdf5object=hdf[eventdectionreadstring]
        #print "Got event location"
        for x in ('start_mux','end_mux','abasic_event_index','abasic_found','abasic_peak_height','duration','hairpin_event_index','hairpin_found','hairpin_peak_height','hairpin_polyt_level','median_before','read_number','scaling_used','start_time'):
            if (x in hdf5object.attrs.keys() ):
                value=str(hdf5object.attrs[x])
                #print x, value
                general_hash.update({x:value})
        #Specific to catch read_id as different class:
        for x in ('read_id'):
            if (x in hdf5object.attrs.keys() ):
                value=str(hdf5object.attrs[x])
                #print 'read_name', value
                general_hash.update({'read_name':value})
        #Add pass flag to general_hash
        general_hash.update({'pass':passcheck})
        general_hash.update({'exp_start_time':tracking_id_hash['exp_start_time']})
        general_hash.update({'1minwin':int(hdf5object.attrs['start_time']/float(tracking_id_hash['sampling_rate'])/60)})#'1minwin':int(template_start/(60))
        general_hash.update({'5minwin':int(hdf5object.attrs['start_time']/float(tracking_id_hash['sampling_rate'])/60/5)})#'1minwin':int(template_start/(60))
        general_hash.update({'10minwin':int(hdf5object.attrs['start_time']/float(tracking_id_hash['sampling_rate'])/60/10)})#'1minwin':int(template_start/(60))
        general_hash.update({'15minwin':int(hdf5object.attrs['start_time']/float(tracking_id_hash['sampling_rate'])/60/15)})#'1minwin':int(template_start/(60))

        #if ('start_mux' in hdf5object.attrs.keys() ):
        #    start_mux=str(hdf5object.attrs['start_mux'])
            #print "start_mux", start_mux
        #    general_hash.update({'start_mux':start_mux})
        #if ('end_mux' in hdf5object.attrs.keys() ):
        #    stop_mux=str(hdf5object.attrs['end_mux'])
            #print "stop_mux", stop_mux
        #    general_hash.update({'end_mux':stop_mux})

    ### load general_hash into mysql
    mysql_load_from_hashes(cursor,"config_general", general_hash)

    ## get all the basecall summary split hairpin data
    basecall_summary_fields=['abasic_dur','abasic_index','abasic_peak','duration_comp','duration_temp','end_index_comp','end_index_temp','hairpin_abasics','hairpin_dur','hairpin_events','hairpin_peak','median_level_comp','median_level_temp','median_sd_comp','median_sd_temp','num_comp','num_events','num_temp','pt_level','range_comp','range_temp','split_index','start_index_comp','start_index_temp']
    basecall_summary_hash=make_hdf5_object_attr_hash(hdf[basecalldir+'Summary/split_hairpin'],basecall_summary_fields)

    ## adding info about other the basecalling itself
    if (basecalldir+'Summary/basecall_1d_complement' in hdf):
        hdf5object=hdf[basecalldir+'Summary/basecall_1d_complement']
        #print "Got event location"
        for x in ('drift','mean_qscore','num_skips','num_stays','scale','scale_sd','sequence_length','shift','strand_score','var','var_sd'):
            if (x in hdf5object.attrs.keys() ):
                value=str(hdf5object.attrs[x])
                #print x, value
                basecall_summary_hash.update({x+"C":value})

    ## adding info about other the basecalling itself
    if (basecalldir+'Summary/basecall_1d_template' in hdf):
        hdf5object=hdf[basecalldir+'Summary/basecall_1d_template']
        #print "Got event location"
        for x in ('drift','mean_qscore','num_skips','num_stays','scale','scale_sd','sequence_length','shift','strand_score','var','var_sd'):
            if (x in hdf5object.attrs.keys() ):
                value=str(hdf5object.attrs[x])
                #print x, value
                basecall_summary_hash.update({x+"T":value})

    if (basecalldir+'Summary/basecall_2d' in hdf):
        hdf5object=hdf[basecalldir+'Summary/basecall_2d']
        #print "Got event location"
        for x in ('mean_qscore','sequence_length'):
            if (x in hdf5object.attrs.keys() ):
                value=str(hdf5object.attrs[x])
                #print x, value
                basecall_summary_hash.update({x+"2":value})

    ## Adding key indexes and time stamps
    basecall_summary_hash.update({'basename_id':basenameid})
    basecall_summary_hash.update({'pass':passcheck})
    basecall_summary_hash.update({'exp_start_time':tracking_id_hash['exp_start_time']})
    basecall_summary_hash.update({'1minwin':general_hash['1minwin']})
    basecall_summary_hash.update({'5minwin':general_hash['5minwin']})
    basecall_summary_hash.update({'10minwin':general_hash['10minwin']})
    basecall_summary_hash.update({'15minwin':general_hash['15minwin']})
    #print basecall_summary_hash

    ## load basecall summary hash into mysql
    mysql_load_from_hashes(cursor,"basecall_summary",basecall_summary_hash)

    ## see if there is any barcoding info to addd
    barcode_hash=dict()
    for x in range(0,9):
        string='/Analyses/Barcoding_00%s/Summary/barcoding' % (x )
        #print string
        if (string in hdf):
            #print "barcode", string
            barcode_hash=make_hdf5_object_attr_hash(hdf[string],('pos0_start','score','design','pos1_end','pos0_end','pos1_start','variant','barcode_arrangement') )
            barcode_hash.update({'basename_id':basenameid})
            mysql_load_from_hashes(cursor,"barcode_assignment", barcode_hash)
            #print barcode_hash
            #for bk in barcode_hash.keys():
            #    print bk, barcode_hash[bk], type(barcode_hash[bk])
            break

    ############# Do model details ##################
    if (args.telem is True):
        if (dbname not in dbcheckhash["modelcheck"]):
            dbcheckhash["modelcheck"][dbname]=dict()

        log_string=basecalldir+'Log'
        if (log_string in hdf):
            log_data = str(hdf[log_string][()])
            #print type(log), log
            lines = log_data.split('\n')
            template_model=None
            complement_model=None
            for l in lines:
                t=re.match(".*Selected model: \"(.*template.*)\".", l)
                if t:
                    template_model=t.group(1)
                c=re.match(".*Selected model: \"(.*complement.*)\".", l)
                if c:
                    complement_model=c.group(1)

            if (template_model is not None):
                sql="INSERT INTO %s (basename_id,template_model,complement_model) VALUES ('%s','%s',NULL)" % ("model_list", basenameid,template_model)
                if (template_model not in dbcheckhash["modelcheck"][dbname]):
                    location=basecalldir+'BaseCalled_template/Model'
                    if location in hdf:
                        upload_model_data("model_data", template_model, location, hdf, cursor)
                        dbcheckhash["modelcheck"][dbname][template_model]=1

                if (complement_model is not None):
                    sql = "INSERT INTO %s (basename_id,template_model,complement_model) VALUES ('%s','%s','%s')" % ("model_list", basenameid,template_model,complement_model)
                    if (complement_model not in dbcheckhash["modelcheck"][dbname]):
                        location=basecalldir+'BaseCalled_complement/Model'
                        if location in hdf:
                            upload_model_data("model_data", complement_model, location, hdf, cursor)
                            dbcheckhash["modelcheck"][dbname][complement_model]=1

                cursor.execute(sql)
                db.commit()

    ############################################################
    readtypes = {'basecalled_template' : basecalldir+'BaseCalled_template/',
    'basecalled_complement' : basecalldir+'BaseCalled_complement/',
    'basecalled_2d' : basecalldir+'BaseCalled_2D/'}

    fastqhash=dict()
    #tel_sql_list=list()
    tel_data_hash=dict()
    template_start=0
    for readtype, location in readtypes.iteritems():
        if (location in hdf):
            fastq = hdf[location+'Fastq'][()]
            try:
                rec=SeqIO.read(StringIO(fastq), "fastq")
            except Exception, err:
                err_string = "%s:\tError reading fastq oject from base: %s type: %s error: %s" % (time.strftime('%Y-%m-%d %H:%M:%S'), basename, readtype, err)
                print >>sys.stderr, err_string
                with open(dbcheckhash["logfile"][dbname],"a") as logfilehandle:
                    logfilehandle.write(err_string+os.linesep)
                    logfilehandle.close()
                continue

            sequence = str(rec.seq)
            seqlen = len(sequence)
            rec.id=basename+"."+readtype

            qual=chr_convert_array(rec.letter_annotations["phred_quality"])
            fastqhash[rec.id]={"quals":rec.letter_annotations["phred_quality"], "seq":sequence}

            if (location+'Alignment' in hdf): # so its 2D
                #print "we're looking at a 2D read",template_start,"\n\n"
                mysql_load_from_hashes(cursor,readtype, {'basename_id':basenameid,'seqid':rec.id,'sequence':sequence,'qual':qual,'start_time':template_start,'seqlen':seqlen,'exp_start_time':tracking_id_hash['exp_start_time'],'1minwin':int(template_start/(60)),'5minwin':int(template_start/(5*60)),'10minwin':int(template_start/(10*60)),'15minwin':int(template_start/(15*60)),'pass':passcheck})
                if (args.telem is True):
                    alignment = hdf[location+'Alignment'][()]
                    #print "ALIGNMENT", type(alignment)
                    channel = general_hash["channel"][-1]
                    tel_data_hash[readtype]=[basenameid,channel,alignment]
                    #upload_2dalignment_data(basenameid,channel,alignment,db)
                    #tel_sql_list.append(t_sql)

            complement_and_template_fields=['basename','seqid','duration','start_time','scale','shift','gross_shift','drift','scale_sd','var_sd','var','sequence','qual']
            if (location+'Events' in hdf and location+'Model' in hdf): # so its either template or complement
                events_hash=make_hdf5_object_attr_hash(hdf[location+'Events'], complement_and_template_fields)
                model_hash=make_hdf5_object_attr_hash(hdf[location+'Model'], complement_and_template_fields)
                ##Logging the start time of a template read to pass to the 2d read in order to speed up mysql processing
                if (readtype=="basecalled_template"):
                    template_start = events_hash['start_time']
                events_hash.update(model_hash)
                events_hash.update({'basename_id':basenameid,'seqid':rec.id,'sequence':sequence,'qual':qual,'seqlen':seqlen, '1minwin':int(events_hash['start_time']/(60)),'5minwin':int(events_hash['start_time']/(5*60)),'10minwin':int(events_hash['start_time']/(10*60)),'15minwin':int(events_hash['start_time']/(15*60))})
                events_hash.update({'exp_start_time':tracking_id_hash['exp_start_time'],'pass':passcheck})
                mysql_load_from_hashes(cursor, readtype, events_hash)

                ###### This inserts telemetry data. It is optional under the flags above.
                ###### Modified to calculate some means and averages - so we are going to do this everytime
                #if (args.telem is True):
                    #print "start telem",  (time.time())-starttime
                    ### Do Events
                events = hdf[location+'Events'][()]
                tablechannel = readtype + "_" + general_hash["channel"][-1]
                tel_data_hash[readtype]=[basenameid,tablechannel,events]
                ## We want to calculate the mean current for a read here... how do we do that?
                #eventcounter=0
                #totalcurrent=0
                #meanlist=list()
                #for event in events:
                #    eventcounter+=1
                #    totalcurrent=totalcurrent + event[0]
                #    meanlist.append(event[0])
                #print numpy.median(numpy.array(meanlist))
                #print basenameid, basename,readtype,eventcounter,totalcurrent/eventcounter

    ##########################################################
    if (dbname in ref_fasta_hash): # so we're doing an alignment
        if (fastqhash): # sanity check for the quality scores in the hdf5 file. this will not exist if it's malformed.
            if (args.last_align is True):
                if (args.verbose is True):
                    print "aligning...."
                init_last_threads(connection_pool[dbname], fastqhash, basename, basenameid, dbname)
            if (args.bwa_align is True):
                if (args.verbose is True):
                    print "aligning...."
                init_bwa_threads(connection_pool[dbname], fastqhash, basename, basenameid, dbname)
            #for seqid in fastqhash.keys():    # use this for debugging instead of lines above that use threading
            #    #if ("template" in seqid):
            #    do_last_align(seqid, fastqhash[seqid], basename, basenameid, dbname, db)
            #    do_bwa_align(seqid, fastqhash[seqid], basename, basenameid, dbname, db)
    hdf.close()


    if (args.telem is True):
        init_tel_threads2(connection_pool[dbname], tel_data_hash)

#####################################################

def do_bwa_align(seqid, fastqhash, basename, basenameid, dbname, db):
    cursor=db.cursor()
    #Op BAM Description
    #M 0 alignment match (can be a sequence match or mismatch)cur
    #I 1 insertion to the reference
    #D 2 deletion from the reference
    #N 3 skipped region from the reference
    #S 4 soft clipping (clipped sequences present in SEQ)
    #H 5 hard clipping (clipped sequences NOT present inSEQ)
    #P 6 padding (silent deletion from padded reference)
    #= 7 sequence match
    #X 8 sequence mismatch

    colstring='basename_id,refid,alignnum,covcount,alignstrand,score,seqpos,refpos,seqbase,refbase,seqbasequal,cigarclass'
    qualscores=fastqhash["quals"]
    options="-"+(args.bwa_options.replace(","," -"))
    #print options
    #read='>testread\nGGCATGACATAAACAAACGTACTTGCCTGTCTGATATATCTTCGGCGTCTTGATCGTAGTTATACGTCATCATAGTGCGGGCCGCGTATTTGTGTTGTCG'
    #cmd='bwa mem -x ont2d -T0 %s.bwa.index %s.fasta ' % (ref_fasta_hash[dbname]["prefix"], basename)
    #cmd='cat %s.fasta | bwa mem -x ont2d -T0 %s.bwa.index -' % (basename, ref_fasta_hash[dbname]["prefix"])
    read=">%s \r\n%s" % (seqid,fastqhash["seq"])
    cmd='bwa mem -x ont2d %s %s -' % (options, ref_fasta_hash[dbname]["bwa_index"])
    #print cmd
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE, shell=True)
    out, err = proc.communicate(input=read)
    status = proc.wait()
    #print "BWA Error", err
    sam=out.encode('utf-8')
    samdata=sam.splitlines()
    for line in samdata:
        #print line
        if not line.startswith('@'):
            line=line.strip('\n')
            record=line.split("\t")
            #print "RECORD", len(record)
            if (record[2] is not '*'):
                qname=record[0]
                flag=int(record[1])
                rname=record[2]
                refid=ref_fasta_hash[dbname]["refid"][rname]
                pos=int(record[3])
                mapq=int(record[4])
                cigar=record[5]
                rnext=record[6]
                pnext=record[7]
                tlen=int(record[8])
                seq=record[9]
                qual=record[10]
                n_m=record[11]
                m_d=record[12]
                a_s=record[13]
                x_s=record[14]

                align_strand=str()
                strand=str()

                if (flag==0 or flag==2048):
                    strand="+"
                    align_strand="F"

                if (flag==16 or flag==2064):
                    strand="-"
                    align_strand="R"

                tablename=str()
                if (qname.endswith("2d")):
                    tablename='align_sam_basecalled_2d'
                if (qname.endswith("complement")):
                    tablename='align_sam_basecalled_complement'
                if (qname.endswith("template")):
                    tablename='align_sam_basecalled_template'
                sql= "INSERT INTO %s (basename_id,qname,flag,rname,pos,mapq,cigar,rnext,pnext,tlen,seq,qual,N_M,M_D,A_S,X_S) VALUES (%d,\'%s\',%d,\'%s\',%d,%d,\'%s\',\'%s\',\'%s\',%d,\'%s\',\'%s\',\'%s\',\'%s\',\'%s\',\'%s\')" % (tablename,basenameid,qname,flag,rname,pos,mapq,cigar,rnext,pnext,tlen,seq,qual,n_m,m_d,a_s,x_s)
                #print sql
                cursor.execute(sql)
                db.commit()
                #print tablename

                ##################
                r_pos=int(record[3])-1
                readbases=list(record[9])
                #translate_cigar_mdflag_to_reference(cigar,m_d,r_pos,readbases)
                align_info=translate_cigar_mdflag_to_reference(cigar,m_d,r_pos,readbases)
                #result={"q_start":q_start, "q_stop":q_stop, "q_start_base":r_array[0],"q_stop_base":r_array[-1], "r_start":r_start, "r_stop":r_stop, "r_start_base":r_array[0],"r_stop_base":r_array[-1]  }
                ####### do 5' 3' aligned read base position calc. ########
                tablename = 'last_align_'+qname.rsplit('.', 1)[1]
                #lo.pprint tablename
                if (args.verbose is True):
                    align_message="%s\tAligned:%s:%s-%s (%s) " % (qname, rname, align_info["r_start"], align_info["r_stop"], strand)
                    print align_message
                #print line

                ####I think this is the point we know a read is aligning.

                sql = "UPDATE "+dbname+"."+qname.split('.')[-1]+" SET align='1' WHERE basename_id=\'%s\'" % (basenameid) # ML
                #print sql
                #sys.exit()
                cursor.execute(sql)
                db.commit()

                if (flag==0): # so it's a primary alignment, POSITIVE strand
                    fiveprimetable = tablename+"_5prime"
                    threeprimetable = tablename+"_3prime"
                    #print "Qs", len(qualscores), int(align_info["q_stop"])
                    ### five prime
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % '1' # alignnum
                    valstring+= "%s," % '0' # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % mapq # score
                    valstring+= "%s," % ( align_info["q_start"] ) # seqpos
                    valstring+= "%s," % ( align_info["r_start"] ) # refpos
                    valstring+= "\'%s\'," % ( align_info["q_start_base"] ) # seqbase
                    valstring+= "\'%s\'," % ( align_info["r_start_base"] ) # refbase
                    valstring+= "%s," % qualscores[int(align_info["q_start"])-1] # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    #primes[tablename]['fiveprime']['string']=valstring
                    sql="INSERT INTO %s (%s) VALUES %s" % (fiveprimetable, colstring, valstring)
                    #print "B", sql
                    cursor.execute(sql)
                    db.commit()


                    ### three prime
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % '1' # alignnum
                    valstring+= "%s," % '0' # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % mapq # score
                    valstring+= "%s," % (align_info["q_stop"] ) # seqpos
                    valstring+= "%s," % (align_info["r_stop"] ) # refpos
                    valstring+= "\'%s\'," % (align_info["q_stop_base"] ) # seqbase
                    valstring+= "\'%s\'," % (align_info["r_stop_base"] ) # refbase
                    valstring+= "%s," % qualscores[int(align_info["q_stop"])-1]  # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    sql="INSERT INTO %s (%s) VALUES %s" % (threeprimetable, colstring, valstring)
                    #print "B", sql
                    cursor.execute(sql)
                    db.commit()

                if (flag==16 ): # It's a primary alignment on the NEGATIVE strand
                    fiveprimetable = tablename+"_5prime"
                    threeprimetable = tablename+"_3prime"
                    #print "Qs", len(qualscores), int(align_info["q_stop"])
                    ### five prime
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % '1' # alignnum
                    valstring+= "%s," % '0' # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % mapq # score
                    valstring+= "%s," % ( align_info["q_start"] ) # seqpos
                    valstring+= "%s," % ( align_info["r_stop"] ) # refpos
                    valstring+= "\'%s\'," % ( align_info["q_start_base"] ) # seqbase
                    valstring+= "\'%s\'," % ( align_info["r_stop_base"] ) # refbase
                    valstring+= "%s," % qualscores[int(align_info["q_stop"])-1] # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    #primes[tablename]['fiveprime']['string']=valstring
                    sql="INSERT INTO %s (%s) VALUES %s" % (fiveprimetable, colstring, valstring)
                    #print "B", sql
                    cursor.execute(sql)
                    db.commit()

                    ### three prime
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % '1' # alignnum
                    valstring+= "%s," % '0' # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % mapq # score
                    valstring+= "%s," % (align_info["q_stop"] ) # seqpos
                    valstring+= "%s," % (align_info["r_start"] ) # refpos
                    valstring+= "\'%s\'," % (align_info["q_stop_base"] ) # seqbase
                    valstring+= "\'%s\'," % (align_info["r_start_base"] ) # refbase
                    valstring+= "%s," % qualscores[int(align_info["q_stop"])-1]  # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    sql="INSERT INTO %s (%s) VALUES %s" % (threeprimetable, colstring, valstring)
                    #print "B", sql
                    cursor.execute(sql)
                    db.commit()
                ##################################

######################################################

def translate_cigar_mdflag_to_reference(cigar,m_d,r_start,readbases):

    q_pos=0
    r_pos=r_start
    r_array=list()
    q_array=list()

    cigparts = re.split('([A-Z])', cigar)
    cigsecs=[cigparts[x:x+2] for x in xrange(0, len(cigparts)-1, 2)]

    for cig in cigsecs:
        #print "cigar point:", cigarpoint
        cigartype = cig[1]
        cigarpartbasecount=int(cig[0])
        if (cigartype is "S"): # not aligned read section
            q_pos+=cigarpartbasecount

        if (cigartype is "M"): # so its not a deletion or insertion. Its 0:M
            for q in xrange(q_pos, (q_pos+cigarpartbasecount) ):
                q_array.append(readbases[q])
            for r in xrange(r_pos, (r_pos+cigarpartbasecount) ):
                r_array.append("X")
            q_pos+=cigarpartbasecount
            r_pos+=cigarpartbasecount

        if (cigartype is "I"):
            for q in xrange(q_pos, (q_pos+cigarpartbasecount) ):
                q_array.append(readbases[q])
            for r in xrange(r_pos, (r_pos+cigarpartbasecount) ):
                r_array.append("-")
            q_pos+=cigarpartbasecount

        if (cigartype is "D"):
            for q in xrange(q_pos, (q_pos+cigarpartbasecount) ):
                q_array.append("-")
            for r in xrange(r_pos, (r_pos+cigarpartbasecount) ):
                #rstring+=str(refbases[r])
                r_array.append("X")
            r_pos+=cigarpartbasecount

    #print "QUERY:", ''.join(q_array)
    #print "REFF1:", ''.join(r_array)
    #####################################################
    for x in range(len(q_array)):
        if (r_array[x] is not "-"):
            if (q_array[x] is not "-"):
                r_array[x]=q_array[x]
    #print "REFF2:", ''.join(r_array)
    #####################################################
    mdparts = re.split('(\d+|MD:Z:)', m_d)
    a=0
    for m in mdparts:
        if (m.isdigit()):
            for b in range(int(m)):
                if (r_array[(a+b)] is "-"):
                    while (r_array[(a+b)] is "-"):
                        a+=1
            a+=int(m)

        else:
            if (m is "A" or m is "T" or m is "C" or m is "G"):
                if (r_array[a] is "-"):
                    while (r_array[a] is "-"):
                        a+=1
                r_array[a]=m
                #r_array[a]="o"
                a+=1

            else:
                if (m.startswith('^')):
                    ins=list(m[1:])
                    for x in range(len(ins)):
                        r_array[a]=ins[x]
                        #r_array[a]='i'
                        a+=1
    #print "QUERY:", ''.join(q_array)
    #print "REFF3:", ''.join(r_array)
    ## get the first position of the query sequence that is aligned
    q_start=0
    if (cigsecs[0][1] is "S" or cigsecs[0][1] is "H"):
        q_start=cigsecs[0][0]
    ######
    q_stop=q_pos
    r_stop=r_pos
    result={"q_start":int(q_start), "q_stop":int(q_stop), "q_start_base":r_array[0],"q_stop_base":r_array[-1], "r_start":(int(r_start+1)), "r_stop":(int(r_stop+1)), "r_start_base":r_array[0],"r_stop_base":r_array[-1]  }
    return result


######################################################################

def create_align_table_sam(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'qname VARCHAR(150)',
    'flag INT(4) ',
    'rname VARCHAR(150)',
    'pos INT(7)',
    'mapq INT(3)',
    'cigar TEXT',
    'rnext VARCHAR(100)',
    'pnext INT(4)',
    'tlen INT(4)',
    'seq TEXT',
    'qual TEXT',
    ### now add extra columns as needed
    'n_m VARCHAR(10)',
    'm_d TEXT',
    'a_s VARCHAR(10)',
    'x_s VARCHAR(10)')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

###########################################
class last_threader(threading.Thread):
    def __init__(self,seqid,fastqdata,basename,basenameid,dbname,db):
        threading.Thread.__init__(self)
        self.seqid=seqid
        self.fastqdata=fastqdata
        self.basename=basename
        self.basenameid=basenameid
        self.dbname=dbname
        self.db=db

    def run(self):
        do_last_align(self.seqid,self.fastqdata,self.basename,self.basenameid,self.dbname,self.db)

###########################################

class bwa_threader(threading.Thread):
    def __init__(self,seqid,fastqdata,basename,basenameid,dbname,db):
        threading.Thread.__init__(self)
        self.seqid=seqid
        self.fastqdata=fastqdata
        self.basename=basename
        self.basenameid=basenameid
        self.dbname=dbname
        self.db=db

    def run(self):
        do_bwa_align(self.seqid,self.fastqdata,self.basename,self.basenameid,self.dbname,self.db)

#####################################################

class tel_threader(threading.Thread):
    def __init__(self,db,sql):
        threading.Thread.__init__(self)
        self.db=db
        self.sql=sql
    def run(self):
        run_insert(self.db, self.sql)

######################################################

def run_insert(dbx, sql):
    try:
        cursorx = dbx.cursor()
        cursorx.execute(sql)
        dbx.commit()
        cursorx.close()
    except Exception, err:
        print "mysql pool failed", err
    return

#######################################################
class tel_twodalign_threader(threading.Thread):
    def __init__(self,basenameid,channel,events,db):
        threading.Thread.__init__(self)
        self.basenameid=basenameid
        self.channel=channel
        self.events=events
        self.db=db
    def run(self):
        upload_2dalignment_data(self.basenameid,self.channel,self.events,self.db)

#######################################################
class tel_template_comp_threader(threading.Thread):
    def __init__(self,basenameid,tablechannel,events,db):
        threading.Thread.__init__(self)
        self.basenameid=basenameid
        self.tablechannel=tablechannel
        self.events=events
        self.db=db
    def run(self):
        upload_telem_data(self.basenameid,self.tablechannel,self.events,self.db)

#######################################################
def init_tel_threads2(connections, tel_data):
    backgrounds=[]
    d=0
    for read_type in tel_data.keys():
        #if (args.verbose is True):
        #    print "using TEL pool thread", d
        db=connections[d]
        #print "connection: %d, %s"%(d, db)
        if (read_type is "basecalled_2d"):
            background=tel_twodalign_threader(tel_data[read_type][0],tel_data[read_type][1],tel_data[read_type][2],db)
        if (read_type is "basecalled_template"):
            background=tel_template_comp_threader(tel_data[read_type][0],tel_data[read_type][1],tel_data[read_type][2],db)
        if (read_type is "basecalled_complement"):
            background=tel_template_comp_threader(tel_data[read_type][0],tel_data[read_type][1],tel_data[read_type][2],db)
        background.start()
        backgrounds.append(background)
        d+=1
    for background in backgrounds:
        background.join()


#######################################################
def init_tel_threads(connections, sqls):
    backgrounds = []
    for d in xrange(0, len(sqls)):
        #if (args.verbose is True):
        #    print "using pool thread", d
        db=connections[d]
        sql=sqls[d]
        #print "connection: %d, %s"%(d, db)
        background = tel_threader(db, sql)
        background.start()
        backgrounds.append(background)

    for background in backgrounds:
        background.join()

########################################################

def init_last_threads(connections, fastqhash, basename, basenameid,dbname):
    backgrounds=[]
    d=0
    for seqid in fastqhash.keys():
        db=connections[d]
        fastqdata=fastqhash[seqid]
        background = last_threader(seqid, fastqdata, basename, basenameid, dbname, db)
        background.start()
        backgrounds.append(background)
        d+=1
    for background in backgrounds:
        background.join()

########################################################

def init_bwa_threads(connections, fastqhash, basename, basenameid,dbname):
    backgrounds = []
    d=0
    for seqid in fastqhash.keys():
        db=connections[d]
        fastqdata=fastqhash[seqid]
        background = bwa_threader(seqid, fastqdata, basename, basenameid, dbname, db)
        background.start()
        backgrounds.append(background)
        d+=1
    for background in backgrounds:
        background.join()

#####################################################

def upload_2dalignment_data(basenameid, channel, alignment,db):
    cursor=db.cursor()
    sqlarray=list()
    for i in alignment:
        val_str = "(%d,%d,%d,'%s')" % (basenameid, i[0],i[1],i[2])
        sqlarray.append(val_str)
    stringvals=','.join(sqlarray)
    sql = 'INSERT INTO caller_basecalled_2d_alignment_%s (basename_id,template,complement,kmer) VALUES %s;' % (channel, stringvals)
    #print sql
    cursor.execute(sql)
    db.commit()
    #return sql

#####################################################

def upload_telem_data(basenameid,readtype,events, db):
    cursor=db.cursor()
    ###Going to be my worker thread function """
    sqlarray=list()
    #print "EVENTS LEN", len(events[0])
    if (len(events[0]) == 14):
        for i in events:
            val_str = "(%d,%f,%f,%f,%f,'%s',%f,%d,%f,'%s',%f,%f,%f,%f,%f, 0)" % (basenameid, i[0],i[1],i[2],i[3],i[4],i[5],i[6],i[7],i[8],i[9],i[10],i[11],i[12],i[13])
            sqlarray.append(val_str)
    else:
        #print "LEN", len(events[0])
        for i in events:
                if "weights" in  events.dtype.names:
                    val_str = "(%d,%f,%f,%f,%f,'%s',%f,%d,%f,'%s',%f,%f,%f,%f,%f,0)" % (basenameid, i[0],i[1],i[2],i[3],i[4],i[5],i[6],i[8],i[9],i[10],i[11],i[12],i[13],i[14])
                else:
                    val_str = "(%d,%f,%f,%f,%f,'%s',%f,%d,%f,'%s',%f,%f,%f,%f,%f,%d)" % (basenameid, i[0],i[1],i[2],i[3],i[4],i[5],i[6],i[7],i[8],i[9],i[10],i[11],i[12],i[13],i[14])
                sqlarray.append(val_str)

    stringvals=','.join(sqlarray)
    #print "processed telem",  (time.time())-starttime
    sql = 'INSERT INTO caller_%s (basename_id,mean,start,stdv,length,model_state,model_level,move,p_model_state,mp_state,p_mp_state,p_A,p_C,p_G,p_T,raw_index) VALUES %s;' % (readtype, stringvals)
    cursor.execute(sql)
    db.commit()

#####################################################
def upload_model_data(tablename, model_name, model_location, hdf, cursor):
    table = hdf[model_location][()]
    sqlarray=list()
    for r in table:
        i=list(r)
        if ( len(i) == 6):
            i.insert(1, 0)
        eventdeats = "('"+str(model_name)+"'"
        for j in i:
            if isinstance(j, (int, long, float, complex)):
                eventdeats+= ","+str(j)
            else:
                eventdeats+= ",'"+str(j)+"'"
        eventdeats+=")"
        sqlarray.append(eventdeats)
    stringvals=','.join(sqlarray)
    sql = 'INSERT INTO %s (model,kmer,variant,level_mean,level_stdv,sd_mean,sd_stdv,weight) VALUES %s;' % (tablename, stringvals)
    #print sql
    cursor.execute(sql)
    db.commit()

#####################################################

def do_last_align(qname, fastqhash, basename, basenameid, dbname, db):
    cursor=db.cursor()
    #def do_bwa_align(seqid, fastqhash, basename, basenameid, dbname, cursor):
    #Op BAM Description
    #M 0 alignment match (can be a sequence match or mismatch)
    #I 1 insertion to the reference
    #D 2 deletion from the reference
    #N 3 skipped region from the reference
    #S 4 soft clipping (clipped sequences present in SEQ)
    #H 5 hard clipping (clipped sequences NOT present inSEQ)
    #P 6 padding (silent deletion from padded reference)
    #= 7 sequence match
    #X 8 sequence mismatch
    #align_prefix=ref_basename

    #print "starting alignment", (time.time())-starttime
    #cmd='lastal -s 2 -T 0 -Q 0 -a 1  %s.last.index %s.fasta > %s.temp.maf' %(ref_fasta_hash[dbname]["prefix"], basename, basename)
    #cmd='parallel-fasta -j %s "lastal -s 2 -T 0 -Q 0 -a 1 %s.last.index" < %s.fasta > %s.temp.maf'  %(args.threads, ref_fasta_hash[dbname]["prefix"], basename, basename)
    #print cmd
    #proc = subprocess.Popen(cmd, shell=True)
    #status = proc.wait()

    options="-"+(args.last_options.replace(","," -"))
    cmd=str()
    if (oper is "linux"):
        cmd='lastal %s  %s -' % (options, ref_fasta_hash[dbname]["last_index"])
    if (oper is "windows"):
        cmd='lastal %s  %s ' % (options, ref_fasta_hash[dbname]["last_index"])

    read=">%s \r\n%s" % (qname,fastqhash["seq"])
    #print cmd
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE, shell=True)
    out, err = proc.communicate(input=read)
    #print err
    status = proc.wait()
    maf=out.encode('utf-8')
    lines=maf.splitlines()

    count_read_align_record=dict()
    count_read_aligned_bases=dict()

    colstring='basename_id,refid,alignnum,covcount,alignstrand,score,seqpos,refpos,seqbase,refbase,seqbasequal,cigarclass'
    colstring_maf='basename_id,refid,alignnum,alignstrand,score,r_start,q_start,r_align_len,q_align_len,r_align_string,q_align_string'

    alignedreadids=dict()
    primes=dict()
    #with open(basename+".temp.maf", "r") as lastfile:
    #lines=lastfile.readlines()
    count_read_align_record=0
    #lines=out.splitlines()
    line_number=0
    #print "lines", len(lines)
    while (line_number < len(lines)-2):
        #print lines[line_number]
        #print ">>>", len(lines[line_number]), "<<<"
        if (0<len(lines[line_number]) and lines[line_number][0] is "a" and lines[line_number+1][0] is "s" and lines[line_number+2][0] is "s"):
            #print "num",line_number, line_number+1, line_number+2
            #########
            score=re.split(' |=', lines[line_number])[2]
            r_list = lines[line_number+1].split()
            q_list = lines[line_number+2].split()
            #name start alnSize strand seqSize alignment
            rname = r_list[1]
            rstart = int(r_list[2])
            rlen = int(r_list[3])
            rend = int(r_list[5])
            ###########
            qname = q_list[1]
            qstart = int(q_list[2])
            qlen = int(q_list[3])
            qend = int(q_list[5])
            ###########
            raln= list(r_list[6])
            qaln= list(q_list[6])
            strand = q_list[4]
            ###########

            if (args.verbose is True):
                align_message="%s\tAligned:%s:%s-%s (%s) " % (qname, rname, rstart, (rstart+rlen), strand)
                print align_message
            ####I think this is the point we know a read is aligning.
            #print dbname,qname.split('.')[-1]
            sql = "UPDATE "+dbname+"."+qname.split('.')[-1]+" SET align='1' WHERE basename_id=\"%s\" " % (basenameid) # ML
            cursor.execute(sql)
            db.commit()
            #print lines[line_number]
            #print lines[line_number+1]
            #print lines[line_number+2]

                #########
            count_read_align_record+=1 # count the read id occurances
            #########
            readbases=list(fastqhash["seq"])
            qualscores=fastqhash["quals"]
            #refbases=ref_fasta_hash["seq_len"][rname]
            refid=ref_fasta_hash[dbname]["refid"][rname]
            ###########
            align_strand=''
            ###########
            if (strand is "+"):
                align_strand="F"
            ##########
            if (strand is "-"):
                align_strand="R"

            ####### do 5' 3' aligned read base position calc. ########
            tablename = 'last_align_'+qname.rsplit('.', 1)[1]
            valstring=''

            first_q_align_base_index=int(q_list[2])
            last_q_align_base_index=(int(q_list[2])+int(q_list[3])-1)
            first_refbase=raln[0]
            last_refbase=raln[(len(raln))-1]
            first_refbase_index = rstart+1
            last_refbase_index = (rstart+rlen)

            if (strand is "-"):
                last_q_align_base_index=(int(q_list[5])-int(q_list[2]))-1
                first_q_align_base_index=( int(q_list[5])-int(q_list[2])-int(q_list[3]))
                first_refbase=raln[(len(raln))-1]
                last_refbase=raln[0]
                first_refbase_index = (rstart+rlen)
                last_refbase_index = rstart+1

            if (tablename in primes):
                if ( (first_q_align_base_index+1) <primes[tablename]['fiveprime']['seqpos'] ): # lowest seqpos
                    primes[tablename]['fiveprime']['seqpos']=(first_q_align_base_index+1)
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % count_read_align_record # alignnum
                    valstring+= "%s," % '0' # covcount
                    #valstring+= "%s," % count_read_aligned_bases[(qname,rname,rstart)] # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % score # score
                    valstring+= "%s," % (first_q_align_base_index+1) # seqpos
                    valstring+= "%s," % (first_refbase_index) # refpos
                    valstring+= "\'%s\'," % (readbases[first_q_align_base_index]) # seqbase
                    valstring+= "\'%s\'," % (first_refbase) # refbase
                    valstring+= "%s," % qualscores[first_q_align_base_index] # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    primes[tablename]['fiveprime']['string']=valstring

                if (primes[tablename]['threeprime']['seqpos'] < (last_q_align_base_index+1) ): # lowest seqpos
                    primes[tablename]['threeprime']['seqpos']=(last_q_align_base_index+1)
                    valstring="("
                    valstring+= "%s," % (basenameid) # basename_id
                    valstring+= "%s," % (refid) # refid
                    valstring+= "%s," % count_read_align_record # alignnum
                    valstring+= "%s," % '0' # covcount
                    #valstring+= "%s," % count_read_aligned_bases[(qname,rname,rstart)] # covcount
                    valstring+= "\'%s\'," % (align_strand) # alignstrand
                    valstring+= "%s," % score # score
                    valstring+= "%s," % (last_q_align_base_index+1) # seqpos
                    valstring+= "%s," % (last_refbase_index) # refpos
                    #print (qstart+qlen), len(readbases)
                    valstring+= "\'%s\'," % (readbases[last_q_align_base_index]) # seqbase
                    valstring+= "\'%s\'," % (last_refbase) # refbase
                    valstring+= "%s," % qualscores[last_q_align_base_index] # seqbasequal
                    valstring+= "%s" % ('7') # cigarclass
                    valstring+=")"
                    primes[tablename]['threeprime']['string']=valstring


            if (tablename not in primes):
                primes[tablename]=dict()
                primes[tablename]['fiveprime']=dict()
                primes[tablename]['fiveprime']['seqpos']=(first_q_align_base_index+1)
                valstring="("
                valstring+= "%s," % (basenameid) # basename_id
                valstring+= "%s," % (refid) # refid
                valstring+= "%s," % count_read_align_record # alignnum
                valstring+= "%s," % '0' # covcount
                #valstring+= "%s," % count_read_aligned_bases[(qname,rname,rstart)] # covcount
                valstring+= "\'%s\'," % (align_strand) # alignstrand
                valstring+= "%s," % score # score
                valstring+= "%s," % (first_q_align_base_index+1) # seqpos
                valstring+= "%s," % (first_refbase_index) # refpos
                valstring+= "\'%s\'," % (readbases[first_q_align_base_index]) # seqbase
                valstring+= "\'%s\'," % (first_refbase) # refbase
                valstring+= "%s," % qualscores[first_q_align_base_index] # seqbasequal
                valstring+= "%s" % ('7') # cigarclass
                valstring+=")"
                primes[tablename]['fiveprime']['string']=valstring
                primes[tablename]['threeprime']=dict()
                primes[tablename]['threeprime']['seqpos']=(last_q_align_base_index+1)
                valstring="("
                valstring+= "%s," % (basenameid) # basename_id
                valstring+= "%s," % (refid) # refid
                valstring+= "%s," % count_read_align_record # alignnum
                valstring+= "%s," % '0' # covcount
                #valstring+= "%s," % count_read_aligned_bases[(qname,rname,rstart)] # covcount
                valstring+= "\'%s\'," % (align_strand) # alignstrand
                valstring+= "%s," % score # score
                valstring+= "%s," % (last_q_align_base_index+1) # seqpos
                valstring+= "%s," % (last_refbase_index) # refpos
                #print (qstart+qlen), len(readbases)
                #print len(qualscores), qend, "###"
                valstring+= "\'%s\'," % (readbases[last_q_align_base_index]) # seqbase
                valstring+= "\'%s\'," % last_refbase # refbase
                valstring+= "%s," % qualscores[last_q_align_base_index] # seqbasequal
                valstring+= "%s" % ('7') # cigarclass
                valstring+=")"
                primes[tablename]['threeprime']['string']=valstring
            #############################

            ##### upload MAF ####
            #if (args.upload_maf is True):
            valstring = str()
            valstring+= "%s," % (basenameid) # basename_id
            valstring+= "%s," % (refid) # refid
            valstring+= "%s," % count_read_align_record # alignnum
            valstring+= "\'%s\'," % (align_strand) # alignstrand
            valstring+= "%s," % score # score
            valstring+= "%s," % (rstart) # r_start
            valstring+= "%s," % (qstart) # q_start
            valstring+= "%s," % (rlen) # r_align_len
            valstring+= "%s," % (qlen) # q_align_len
            valstring+= "\'%s\'," % (r_list[6]) # r_align_string
            valstring+= "\'%s\'" % (q_list[6]) # q_align_string
            tablename = 'last_align_maf_'+qname.rsplit('.', 1)[1]
            sql="INSERT INTO %s (%s) VALUES (%s) " % (tablename, colstring_maf, valstring)
            #print sql
            cursor.execute(sql)
            db.commit()

            #####################
            #print "dbname", dbname
            #filehandle=dbcheckhash["mafoutdict"][dbname]
            #filehandle.write(lines[line_number])
            #filehandle.write(lines[line_number+1])
            #filehandle.write(lines[line_number+2]+os.linesep)
            #####################
        line_number+=1

    ##### upload 5' 3' prime ends ####
    for tablename in primes:
        fiveprimetable = tablename+"_5prime"
        threeprimetable = tablename+"_3prime"

        string = primes[tablename]['fiveprime']['string']
        sql="INSERT INTO %s (%s) VALUES %s" % (fiveprimetable, colstring, string)
        #print "L", sql
        cursor.execute(sql)
        db.commit()

        string = primes[tablename]['threeprime']['string']
        sql="INSERT INTO %s (%s) VALUES %s" % (threeprimetable, colstring, string)
        #print "L", sql
        cursor.execute(sql)
        db.commit()
    ###########
    #os.remove(basename+".temp.maf")
    #print "finished alignment", (time.time())-starttime

###########################################################
def file_dict_of_folder(path):

    file_list_dict=dict()
    ref_list_dict=dict()

    global xml_file_dict
    xml_file_dict=dict()

    if os.path.isdir(path):
        print "caching existing fast5 files in: %s" % (path)
        for path, dirs, files in os.walk(path) :
            for f in files:
                if ("downloads" in path ):
                    if ("muxscan" not in f and f.endswith(".fast5") ):
                        file_list_dict[os.path.join(path, f)]=os.stat(os.path.join(path, f)).st_mtime

                    if (args.batch_fasta is True):
                        if ("reference" in path):
                            if ( f.endswith(".fa") or f.endswith(".fasta") or f.endswith(".fna") ):
                                ref_path=path
                                while  ("downloads" not in os.path.split(ref_path)[1]):
                                    ref_path=os.path.split(ref_path)[0]
                                if (ref_path not in ref_list_dict):
                                    ref_list_dict[ref_path]=list()
                                ref_list_dict[ref_path].append(os.path.join(path, f))

                    if ( "XML" in path ):
                        if ( f.endswith(".xml") ):
                            xml_path=path
                            while  ("downloads" not in os.path.split(xml_path)[1]):
                                #print xml_path, os.path.split(xml_path), len (os.path.split(xml_path))
                                xml_path=os.path.split(xml_path)[0]
                                #print "FINAL", xml_path
                            try:
                                xmlraw=open((os.path.join(path, f)), 'r').read()
                                xmldict = xmltodict.parse(xmlraw)
                                if (xml_path not in xml_file_dict):
                                    xml_file_dict[xml_path]=dict()
                                    xml_file_dict[xml_path]["study"]=dict()
                                    xml_file_dict[xml_path]["experiment"]=dict()
                                    xml_file_dict[xml_path]["run"]=dict()
                                    xml_file_dict[xml_path]["sample"]=dict()

                                if ('STUDY_SET' in xmldict):
                                    #print "STUDY", f
                                    primary_id=xmldict['STUDY_SET']['STUDY']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "STUDY_ID", primary_id
                                    title=xmldict['STUDY_SET']['STUDY']['DESCRIPTOR']['STUDY_TITLE']
                                    #print "TITLE", title
                                    abstr=xmldict['STUDY_SET']['STUDY']['DESCRIPTOR']['STUDY_ABSTRACT']
                                    #print "ABSTRACT", abstr
                                    if (primary_id not in xml_file_dict[xml_path]["study"]):
                                        xml_file_dict[xml_path]["study"][primary_id]=dict()
                                    xml_file_dict[xml_path]["study"][primary_id]["file"]=f
                                    xml_file_dict[xml_path]["study"][primary_id]["xml"]=xmlraw
                                    xml_file_dict[xml_path]["study"][primary_id]["title"]=title
                                    xml_file_dict[xml_path]["study"][primary_id]["abstract"]=abstr
                                    xml_file_dict[xml_path]["study"][primary_id]["path"]=path

                                if ('EXPERIMENT_SET' in xmldict):
                                    #print "EXPERIMENT", f
                                    primary_id=xmldict['EXPERIMENT_SET']['EXPERIMENT']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "EXP_ID", primary_id
                                    study_id= xmldict['EXPERIMENT_SET']['EXPERIMENT']['STUDY_REF']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "STUDY_ID", study_id
                                    sample_id= xmldict['EXPERIMENT_SET']['EXPERIMENT']['DESIGN']['SAMPLE_DESCRIPTOR']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "SAMPLE_ID", sample_id
                                    if (primary_id not in xml_file_dict[xml_path]["experiment"]):
                                        xml_file_dict[xml_path]["experiment"][primary_id]=dict()
                                    xml_file_dict[xml_path]["experiment"][primary_id]["file"]=f
                                    xml_file_dict[xml_path]["experiment"][primary_id]["xml"]=xmlraw
                                    xml_file_dict[xml_path]["experiment"][primary_id]["sample_id"]=sample_id
                                    xml_file_dict[xml_path]["experiment"][primary_id]["study_id"]=study_id
                                    #for a,b in xmldict['EXPERIMENT_SET']['EXPERIMENT'].items():
                                    #    print a,b

                                if ('SAMPLE_SET' in xmldict):
                                    #print "SAMPLE_SET", f
                                    primary_id=xmldict['SAMPLE_SET']['SAMPLE']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "SAMPLE_ID", primary_id
                                    if (primary_id not in xml_file_dict[xml_path]["sample"]):
                                        xml_file_dict[xml_path]["sample"][primary_id]=dict()
                                    xml_file_dict[xml_path]["sample"][primary_id]["file"]=f
                                    xml_file_dict[xml_path]["sample"][primary_id]["xml"]=xmlraw

                                if ('RUN_SET' in xmldict):
                                    #print "RUN", f
                                    primary_id=xmldict['RUN_SET']['RUN']['IDENTIFIERS']['PRIMARY_ID']
                                    exp_id=xmldict['RUN_SET']['RUN']['EXPERIMENT_REF']['IDENTIFIERS']['PRIMARY_ID']
                                    #print "RUN_ID", primary_id
                                    if (primary_id not in xml_file_dict[xml_path]["run"]):
                                        xml_file_dict[xml_path]["run"][primary_id]=dict()
                                    xml_file_dict[xml_path]["run"][primary_id]["xml"]=xmlraw
                                    xml_file_dict[xml_path]["run"][primary_id]["file"]=f
                                    xml_file_dict[xml_path]["run"][primary_id]["exp_id"]=exp_id

                            except Exception, err:
                                err_string="Error with XML file: %s : %s" % (f, err)
                                print >>sys.stderr, err_string
                                continue

    print "found %d existing fast5 files to process first." % (len(file_list_dict) )
    if ( 0<len(xml_file_dict) ):
        print "found %d XML folders." % (len(xml_file_dict))
        counts=dict()
        for xmldir in xml_file_dict.keys():
            for xmltype in xml_file_dict[xmldir].keys():
                if xmltype not in counts:
                    counts[xmltype]=len(xml_file_dict[xmldir][xmltype])
                else:
                    counts[xmltype]+=len(xml_file_dict[xmldir][xmltype])
        for xmltype in counts:
            print "found %d %s xml files." % (counts[xmltype], xmltype)

    if ( 0<len(ref_list_dict)  ):
        print "found %d reference fasta folders." % ( len(ref_list_dict) )
        #print found_ref_note
        for path in ref_list_dict.keys():
            files = ",".join(ref_list_dict[path])
            process_ref_fasta(files)

    #with open(dbcheckhash["logfile"][dbname],"a") as logfilehandle:
    #    logfilehandle.write(found_fast5_note+os.linesep)
    #    logfilehandle.close()

    return file_list_dict

##########################################################
def modify_gru(cursor):

    #### This bit adds columns to Gru.minIONruns ####
    ## Add column 'mt_ctrl_flag' to Gru.minIONruns table if it doesn't exist
    sql ="SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=\"Gru\" AND TABLE_NAME=\"minIONruns\" AND column_name=\"mt_ctrl_flag\" "
    #print sql
    cursor.execute(sql)
    if (cursor.rowcount ==0):
        #print "adding mt_ctrl_flag to Gru.minIONruns"
        sql = "ALTER TABLE Gru.minIONruns ADD mt_ctrl_flag INT(1) DEFAULT 0";
        #print sql
        cursor.execute(sql)
        db.commit()

    ## Add column 'watch_dir' to Gru.minIONruns table if it doesn't exist
    sql ="SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=\"Gru\" AND TABLE_NAME=\"minIONruns\" AND column_name=\"watch_dir\" "
    #print sql
    cursor.execute(sql)
    if (cursor.rowcount ==0):
        #print "adding 'watch_dir' to Gru.minIONruns"
        sql = "ALTER TABLE Gru.minIONruns ADD watch_dir TEXT(200)";
        #print sql
        cursor.execute(sql)
        db.commit()

    ## Add column 'host_ip' to Gru.minIONruns table if it doesn't exist
    sql ="SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=\"Gru\" AND TABLE_NAME=\"minIONruns\" AND column_name=\"host_ip\" "
    #print sql
    cursor.execute(sql)
    if (cursor.rowcount ==0):
        #print "adding mt_ctrl_flag to Gru.minIONruns"
        sql = "ALTER TABLE Gru.minIONruns ADD host_ip TEXT(16)";
        #print sql
        cursor.execute(sql)
        db.commit()

###########################################################
def chr_convert_array(array):
    string=str()
    for val in array:
        string+=chr(val+33)
    return db.escape_string(string)

###########################################################
#def chr_convert_array(array):
#    string='"'
#    for val in array:
#        string+=chr(val+64)
#    string+='"'
#    return string

###########################################################
def make_hdf5_object_attr_hash(hdf5object, fields):
    att_hash=dict()
    for field in fields:
        if (field in hdf5object.attrs.keys() ):
            #print "filed: ",field (args.ref_fasta is not None), hdf5object.attrs[field]
            att_hash[field]=hdf5object.attrs[field]
    return att_hash

##########################################################
def mysql_load_from_hashes(cursor,tablename, data_hash):
    cols=list()
    vals=list()
    for colhead, entry in data_hash.iteritems():
        if isinstance(entry, basestring):
            vals.append("'%s'"  % (entry) )
        else:
            vals.append(str(entry) )
    cols=','.join(data_hash.keys() )
    values=','.join(vals)
    sql ="INSERT INTO %s (%s) VALUES (%s) " % (tablename, cols, values)
    #print sql
    cursor.execute(sql)
    db.commit()
    ids = cursor.lastrowid
    return ids

##########################################################
def process_ref_fasta(ref_fasta):
    print "processing the reference fasta."

    refdict=dict()
    refdict["seq_len"]=dict()
    refdict["refid"]=dict()
    refdict["seq_file"]=dict()
    refdict["seq_file_len"]=dict()
    #refdict["sequence"]=dict()
    refdict["kmer"]=dict()

    files=ref_fasta.split(',')
    ref_basename=''

    if (len(files) ==1):
        ref_basename=os.path.splitext(os.path.basename(files[0]))[0]

    if (1<len(files) ):
        b=os.path.splitext(os.path.basename(files[0]))[0]
        ref_basename="%s_plus_%s_more_seqs" % (os.path.splitext(os.path.basename(files[0]))[0], str(len(files)-1) )

    validated_ref=os.path.join(os.path.sep,valid_ref_dir,ref_basename+"_valid.fasta")

    refdict["big_name"]=validated_ref
    refdict["big_len"]=0
    #refdict["prefix"]=ref_basename
    refdict["path"]=os.path.dirname(files[0])

    if (os.path.isfile(validated_ref) is False or os.stat(validated_ref).st_size==0 ) :
        valid_fasta_handle = open(validated_ref, "w")
        for fasta_file in files:
            print "FASTA file:", fasta_file
            fasta_records = list(SeqIO.parse(fasta_file, "fasta"))
            if (len(fasta_records)==0):
                os.remove(validated_ref)
                err_string="Error with your reference sequence FASTA file: %s: It's an empty file" % (fasta_file)
                print >>sys.stderr, err_string
                sys.exit(1)

            try:
                for record in fasta_records:
                    #ref_fasta_hash["seq_file"][record.id]=os.path.splitext(os.path.basename(fasta_file))[0]
                    if (len(record.seq)==0):
                        os.remove(validated_ref)
                        err_string="Error with your reference sequence FASTA file: %s: SEQID %s" % (fasta_file, record.id)
                        print >>sys.stderr, err_string
                        sys.exit(1)
                    else:
                        seq = record.seq.upper()
                        record.seq=seq
                        record.description=os.path.basename(fasta_file)
                        SeqIO.write([record], valid_fasta_handle, "fasta")

            except Exception, err:
                os.remove(validated_ref)
                err_string="Error with your reference sequence FASTA file: %s: %s" % (fasta_file,err)
                print >>sys.stderr, err_string
                sys.exit(1)
        valid_fasta_handle.close()

    for record in SeqIO.parse(validated_ref, 'fasta'):
        if (args.verbose is True):
            print "processing seq: ", record.id

        refdict["seq_len"][record.id]=len(record.seq)
        disc=re.split('\s+', record.description)[1]
        refdict["seq_file"][record.id]=disc
        refdict["big_len"]+=len(record.seq)
        #####
        #refdict["sequence"][record.id]=record.seq
        #####
        if ( disc in refdict["seq_file_len"]):
            refdict["seq_file_len"][disc]+=len(record.seq)
        else:
            refdict["seq_file_len"][disc]=len(record.seq)

        ### do kmer
        if (args.telem is True):
            recomp = record.seq.reverse_complement()
            km= kmer_count_fasta(record.seq, recomp, 5)
            refdict["kmer"][record.id]=km

    if (args.last_align is True):
        last_index=os.path.join(os.path.sep,last_index_dir,ref_basename+".last.index")
        last_index_file_part=os.path.join(os.path.sep,last_index_dir,ref_basename+".last.index.bck")
        if (os.path.isfile(last_index_file_part) is False or os.stat(last_index_file_part).st_size==0) :
            print "Building LAST index for reference fasta..."
            cmd="lastdb -Q 0 %s %s" %(last_index, validated_ref) # format the database
            if (args.verbose is True):
                print cmd
            proc = subprocess.Popen(cmd, shell=True)
            status = proc.wait()
        refdict["last_index"]=last_index

    if (args.bwa_align is True):
        bwa_index=os.path.join(os.path.sep,bwa_index_dir,ref_basename+".bwa.index")
        bwa_index_file_part=os.path.join(os.path.sep,bwa_index_dir,ref_basename+".bwa.index.bwt")
        if (os.path.isfile(bwa_index_file_part) is False or os.stat(bwa_index_file_part).st_size==0):
            print "Building BWA index for reference fasta..."
            cmd="bwa index -p %s %s" %(bwa_index, validated_ref) # format the database
            if (args.verbose is True):
                print cmd
            proc = subprocess.Popen(cmd, shell=True)
            status = proc.wait()
        refdict["bwa_index"]=bwa_index

    print "finished processing reference fasta."
    ref_fasta_hash[ref_basename]=refdict


########################################################

def create_barcode_table(tablename, cursor):
    fields=(
    'basename_id INT(10), PRIMARY KEY(basename_id)',
    'pos0_start INT(5) NOT NULL',
    'score INT(6) NOT NULL',
    'design VARCHAR(10) NOT NULL',
    'pos1_end INT(5) NOT NULL',
    'pos0_end INT(5) NOT NULL',
    'pos1_start INT(5) NOT NULL',
    'variant VARCHAR(8) NOT NULL',
    'barcode_arrangement VARCHAR(12) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

########################################################

def create_xml_table(tablename, cursor):
    fields=(
    'xmlindex INT(11) NOT NULL AUTO_INCREMENT, PRIMARY KEY(xmlindex)',
    'type VARCHAR(20) NOT NULL',
    'primary_id VARCHAR(30) NOT NULL',
    'filename VARCHAR(30) NOT NULL',
    'xml TEXT DEFAULT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

########################################################

def create_comment_table_if_not_exists(tablename, cursor):
    fields=(
    'comment_id INT(11) NOT NULL AUTO_INCREMENT, PRIMARY KEY(comment_id)',
    'runindex INT(11) NOT NULL',
    'runname TEXT NOT NULL',
    'user_name TEXT NOT NULL',
    'date DATETIME NOT NULL',
    'comment TEXT NOT NULL',
    'name TEXT NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB DEFAULT CHARSET=utf8" % (tablename, colheaders)
    filterwarnings('ignore', "Table 'comments' already exists")
    cursor.execute(sql)

########################################################

def create_general_table( tablename, cursor ):
    fields=(
    'basename_id INT(10) NOT NULL, PRIMARY KEY(basename_id)',
    'basename VARCHAR(150) NOT NULL, UNIQUE KEY(basename)', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'local_folder VARCHAR(50) NOT NULL',
    'workflow_script VARCHAR(50) DEFAULT NULL', #  = basecall_2d_workflow.py"config_general"
    'workflow_name VARCHAR(50) NOT NULL', # = Basecall_2D_000
    'read_id INT(4) NOT NULL', #  = 10
    'use_local VARCHAR(10) NOT NULL', # = False
    'tag VARCHAR(50) NOT NULL', #= channel_101_read_10
    'model_path VARCHAR(50) NOT NULL', # = /opt/metrichor/model
    'complement_model TEXT(10) NOT NULL', #  = auto
    'max_events INT(10) NOT NULL', #  = 100000
    'input VARCHAR(200) NOT NULL', # = /tmp/input/PLSP57501_17062014lambda_3216_1_ch101_file10_strand.fast5
    'min_events INT(4) NOT NULL', # = 1000
    'config VARCHAR(100) NOT NULL', # = /opt/metrichor/config/basecall_2d.cfg
    'template_model VARCHAR(8) NOT NULL', #  = auto
    'channel INT(4) NOT NULL', #  = 101
    'metrichor_version VARCHAR(10) NOT NULL', # version = 0.8.3
    'metrichor_time_stamp VARCHAR(20) NOT NULL', # time_stamp = 2014-Jul-02 09:10:13
    'abasic_event_index INT(1)',
    'abasic_found INT(1)',
    'abasic_peak_height FLOAT(25,17)',
    'duration INT(15)',
    'hairpin_event_index INT(10)',
    'hairpin_found INT(1)',
    'hairpin_peak_height FLOAT(25,17)',
    'hairpin_polyt_level FLOAT(25,17)',
    'median_before FLOAT(25,17)',
    'read_name VARCHAR(37)',
    'read_number int(10)',
    'scaling_used int(5)',
    'start_mux int(1)',
    'start_time int(20)',
    'end_mux INT(1) DEFAULT NULL',
    'exp_start_time INT(15) NOT NULL', #= 1403015537
    '1minwin INT NOT NULL, INDEX(1minwin)',
    '5minwin INT NOT NULL, INDEX(5minwin)',
    '10minwin INT NOT NULL, INDEX(10minwin)',
    '15minwin INT NOT NULL, INDEX(15minwin)',
    'align INT DEFAULT 0,  INDEX(align)',
    'pass INT(1) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)
    #return fields

##########################################################

def create_trackingid_table(tablename, cursor):
    fields=(
    'basename_id INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(basename_id)', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'basename VARCHAR(150) NOT NULL', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'asic_id BIGINT(15) NOT NULL', #  = 48133
    'asic_id_17 BIGINT(15) ', #  = 48133
    'asic_id_eeprom INT(5) ',
    'asic_temp DOUBLE(4,1) NOT NULL', # = 38.4
    'device_id TEXT(8) NOT NULL', # = MN02935
    'exp_script_purpose VARCHAR(50) NOT NULL',#= sequencing_run
    'exp_script_name VARCHAR(150)', #=./python/recipes/MAP_48Hr_Sequencing_Run_SQK_MAP006.py
    'exp_start_time INT(15) NOT NULL', #= 1403015537
    'flow_cell_id VARCHAR(10) NOT NULL',#
    'heatsink_temp FLOAT(10) NOT NULL', #= 35.625
    'hostname TEXT',
    'run_id TEXT(40) NOT NULL',# = 9be694a4d40804eb6ea5761774723318ae3b3346
    'version_name VARCHAR(30) NOT NULL', # = 0.45.1.6 b201406111512
    'file_path TEXT(300) NOT NULL',
    'channel_number int(7)',
    'digitisation float',
    'offset float',
    'range_val float',
    'sampling_rate float',
    'pass INT(1) NOT NULL',
    'md5sum TEXT(33) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)
    #return fields

########################################################

def create_reference_table(tablename, cursor):
    fields=(
    'refid INT(3) NOT NULL AUTO_INCREMENT, PRIMARY KEY(refid)', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'refname VARCHAR(50), UNIQUE INDEX (refname)',
    'reflen INT(7), INDEX (reflen)',
    'reffile VARCHAR(100), INDEX (reffile)',
    'ref_total_len VARCHAR(100), INDEX (ref_total_len)')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

########################################################

def create_basecalled2d_fastq_table(tablename, cursor):
    fields=(
    #['basename','VARCHAR(300) PRIMARY KEY'], # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'basename_id INT(10) NOT NULL, PRIMARY KEY (basename_id)',
    'seqid VARCHAR(150), UNIQUE INDEX (seqid)', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand.whatever
    'seqlen INT NOT NULL',
    'sequence MEDIUMTEXT',
    'start_time FLOAT(25,17) NOT NULL',# = 2347.2034000000003
    'align INT DEFAULT 0,  INDEX(align)',
    '1minwin INT NOT NULL, INDEX(1minwin)',
    '5minwin INT NOT NULL, INDEX(5minwin)',
    '10minwin INT NOT NULL, INDEX(10minwin)',
    '15minwin INT NOT NULL, INDEX(15minwin)',
    'exp_start_time INT(15) NOT NULL', #= 1403015537
    'qual MEDIUMTEXT','index 10minalign (align,10minwin)',
    'index 1minalign (align,1minwin)',
    'index 15minalign (align,15minwin)',
    'pass INT(1) NOT NULL',
    'index 5minalign (align,5minwin)')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

#######################################################
#['ID', 'INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)'],
def create_events_model_fastq_table(tablename, cursor):
    fields=(
    'basename_id INT(10) NOT NULL, PRIMARY KEY (basename_id)',
    #'basename VARCHAR(300), PRIMARY KEY', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand
    'seqid VARCHAR(150) NOT NULL, UNIQUE INDEX (seqid)', # PLSP57501_17062014lambda_3216_1_ch101_file10_strand.whatever
    'duration FLOAT(25,17) NOT NULL', #= 51.80799999999954
'start_time FLOAT(25,17) NOT NULL',# = 2347.2034000000003
    'scale FLOAT(25,17) NOT NULL', # = 1.0063618778594416
'shift FLOAT(25,17) NOT NULL', #= 0.20855518951022478
'gross_shift FLOAT(25,17) DEFAULT NULL', # = -0.10872176688437207
'drift FLOAT(25,17) NOT NULL',  #= 0.004143787533549812
       'scale_sd FLOAT(25,17) NOT NULL', # = 0.9422581300419306
'var_sd FLOAT(25,17) NOT NULL', # = 1.3286319210403454
'var FLOAT(25,17) NOT NULL', # = 1.0368718353240443
'seqlen INT NOT NULL',
'1minwin INT NOT NULL, INDEX(1minwin)',
'5minwin INT NOT NULL, INDEX(5minwin)',
'10minwin INT NOT NULL, INDEX(10minwin)',
'15minwin INT NOT NULL, INDEX(15minwin)',
'align INT DEFAULT 0,  INDEX(align)',
'pass INT(1) NOT NULL',
'exp_start_time INT(15) NOT NULL', #= 1403015537
    'sequence MEDIUMTEXT DEFAULT NULL',
    'qual MEDIUMTEXT DEFAULT NULL',
    'index 10minalign (align,10minwin)',
    'index 1minalign (align,1minwin)',
    'index 15minalign (align,15minwin)',
    'index 5minalign (align,5minwin)')
    colheaders=','.join(fields)
    sql ="CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################
#['ID', 'INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)'],
def create_align_table(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7), INDEX (basename_id)',
    'refid INT(3) DEFAULT NULL, INDEX (refid)',
    'alignnum INT(4) DEFAULT NULL, INDEX (alignnum)',
    'covcount INT(4) DEFAULT NULL, INDEX (covcount)',
    'alignstrand VARCHAR(1), INDEX (alignstrand)', #index
    'score INT(4), INDEX (score)',
    'seqpos INT(6) DEFAULT NULL, INDEX (seqpos)', # index
    'refpos INT(6) DEFAULT NULL, INDEX (refpos)', # index
    'seqbase VARCHAR(1) DEFAULT NULL, INDEX (seqbase)', # index
    'refbase VARCHAR(1) DEFAULT NULL, INDEX (refbase)', # index
    'seqbasequal INT(2) DEFAULT NULL, INDEX (seqbasequal)',
    'cigarclass VARCHAR(1) DEFAULT NULL, INDEX (cigarclass)', # index
    'index combindex (refid,refpos,cigarclass)') # index for combined queries
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################
def create_align_table_maf(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7), INDEX (basename_id)',
    'refid INT(3) DEFAULT NULL, INDEX (refid)',
    'alignnum INT(4) DEFAULT NULL, INDEX (alignnum)',
    'alignstrand VARCHAR(1) DEFAULT NULL, INDEX (alignstrand)', #index
    'score INT(4), INDEX (score)',
    'r_start INT(7) DEFAULT NULL',
    'q_start INT(5) DEFAULT NULL',
    'r_align_len INT(7) DEFAULT NULL',
    'q_align_len INT(5) DEFAULT NULL',
    'r_align_string MEDIUMTEXT DEFAULT NULL',
    'q_align_string MEDIUMTEXT DEFAULT NULL')
    #'index combindex (refid,refpos,cigarclass)') # index for combined queries
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)


######################################################
def create_caller_table(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'mean FLOAT(25,17) NOT NULL',
    'start FLOAT(25,17) NOT NULL',
    'stdv FLOAT(25,17) NOT NULL',
    'length FLOAT(25,17) NOT NULL',
    'model_state VARCHAR(10) NOT NULL, INDEX (model_state)',
    'model_level FLOAT(25,17) NOT NULL',
    'move INT(64) NOT NULL',
    'p_model_state FLOAT(25,17) NOT NULL',
    'mp_state VARCHAR(10) NOT NULL, INDEX (mp_state)',
    'p_mp_state FLOAT(25,17) NOT NULL',
    'p_A FLOAT(25,17) NOT NULL',
    'p_C FLOAT(25,17) NOT NULL',
    'p_G FLOAT(25,17) NOT NULL',
    'p_T FLOAT(25,17) NOT NULL',
    'raw_index INT(64) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=MyISAM" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################
# This removes indexes (performace improvement?

def create_caller_table_noindex(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL',
    'mean FLOAT(25,17) NOT NULL',
    'start FLOAT(25,17) NOT NULL',
    'stdv FLOAT(25,17) NOT NULL',
    'length FLOAT(25,17) NOT NULL',
    'model_state VARCHAR(10) NOT NULL',
    'model_level FLOAT(25,17) NOT NULL',
    'move INT(64) NOT NULL',
    'p_model_state FLOAT(25,17) NOT NULL',
    'mp_state VARCHAR(10) NOT NULL',
    'p_mp_state FLOAT(25,17) NOT NULL',
    'p_A FLOAT(25,17) NOT NULL',
    'p_C FLOAT(25,17) NOT NULL',
    'p_G FLOAT(25,17) NOT NULL',
    'p_T FLOAT(25,17) NOT NULL',
    'raw_index INT(64) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=MyISAM" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)


#########################################################
def create_2d_alignment_table(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'template INT(5) NOT NULL',
    'complement INT(5) NOT NULL',
    'kmer VARCHAR(10) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################
def create_basecall_summary_info(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'abasic_dur float',
    'abasic_index int',
    'abasic_peak float',
    'duration_comp float',
    'duration_temp float',
    'end_index_comp int',
    'end_index_temp int',
    'hairpin_abasics int',
    'hairpin_dur float',
    'hairpin_events int',
    'hairpin_peak float',
    'median_level_comp float',
    'median_level_temp float',
    'median_sd_comp float',
    'median_sd_temp float',
    'num_comp int',
    'num_events int',
    'num_temp int',
    'pt_level float',
    'range_comp float',
    'range_temp float',
    'split_index int',
    'start_index_comp int',
    'start_index_temp int',

    'driftC float ','mean_qscoreC float','num_skipsC int','num_staysC int','scaleC float','scale_sdC float','sequence_lengthC int','shiftC float','strand_scoreC float','varC float','var_sdC float',
    'driftT float ','mean_qscoreT float','num_skipsT int','num_staysT int','scaleT float','scale_sdT float','sequence_lengthT int','shiftT float','strand_scoreT float','varT float','var_sdT float',

    'mean_qscore2 float','sequence_length2 int',
    'exp_start_time INT(15) NOT NULL', #= 1403015537
    '1minwin INT NOT NULL, INDEX(1minwin)',
    '5minwin INT NOT NULL, INDEX(5minwin)',
    '10minwin INT NOT NULL, INDEX(10minwin)',
    '15minwin INT NOT NULL, INDEX(15minwin)',
    'align INT DEFAULT 0,  INDEX(align)',
    'pass INT(1) NOT NULL',
    )
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################
def create_basic_read_info(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'abasic_event_index INT(1) NOT NULL',
    'abasic_found INT(1) NOT NULL',
    'abasic_peak_height FLOAT(25,17)',
    'duration INT(15)',
    'hairpin_event_index INT(10)',
    'hairpin_found INT(1)',
    'hairpin_peak_height FLOAT(25,17)',
    'hairpin_polyt_level FLOAT(25,17)',
    'median_before FLOAT(25,17)',
    'read_id VARCHAR(37)',
    'read_number int(10)',
    'scaling_used int(5)',
    'start_mux int(1)',
    'start_time int(20)',
    '1minwin INT NOT NULL, INDEX(1minwin)',
    '5minwin INT NOT NULL, INDEX(5minwin)',
    '10minwin INT NOT NULL, INDEX(10minwin)',
    '15minwin INT NOT NULL, INDEX(15minwin)',
    'align INT DEFAULT 0,  INDEX(align)',
    'pass INT(1) NOT NULL',)
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)


######################################################

def create_5_3_prime_align_tables(align_table_in, cursor):

    three_prime_table=align_table_in+"_3prime"
    five_prime_table=align_table_in+"_5prime"
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7) NOT NULL, INDEX (basename_id)',
    'refid INT(3) DEFAULT NULL, INDEX (refid)',
    'alignnum INT(4) DEFAULT NULL, INDEX (alignnum)',
    'covcount INT(4) DEFAULT NULL, INDEX (covcount)',
    'alignstrand VARCHAR(1), INDEX (alignstrand)', #index
    'score INT(4), INDEX (score)',
    'seqpos INT(6) DEFAULT NULL, INDEX (seqpos)', # index
    'refpos INT(6) DEFAULT NULL, INDEX (refpos)', # index
    'seqbase VARCHAR(1) DEFAULT NULL, INDEX (seqbase)', # index
    'refbase VARCHAR(1) DEFAULT NULL, INDEX (refbase)', # index
    'seqbasequal INT(2) DEFAULT NULL, INDEX (seqbasequal)',
    'cigarclass VARCHAR(1) DEFAULT NULL, INDEX (cigarclass)', # index
    'index combindex (refid,refpos,cigarclass)') # index for combined queries
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (three_prime_table, colheaders)
    cursor.execute(sql)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (five_prime_table, colheaders)
    cursor.execute(sql)

########################################################

def create_ref_kmer_table(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'kmer VARCHAR(10) NOT NULL, INDEX (kmer)',
    'refid INT(3) NOT NULL, INDEX (refid)',
    'count INT(7) NOT NULL',
    'total INT(7) NOT NULL',
    'freq float(13,10) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

########################################################

def create_model_list_table(tablename, cursor):
    fields=(
    #'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'basename_id INT(7), PRIMARY KEY(basename_id)',
    'template_model VARCHAR(200), INDEX (template_model)',
    'complement_model VARCHAR(200), INDEX (complement_model)')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

######################################################

def create_model_data_table(tablename, cursor):
    fields=(
    'ID INT(10) NOT NULL AUTO_INCREMENT, PRIMARY KEY(ID)',
    'model VARCHAR(200) NOT NULL, INDEX (model)',
    'kmer VARCHAR(10) NOT NULL, INDEX (kmer)',
    'variant INT(10) NOT NULL',
    'level_mean FLOAT(25,17) NOT NULL',
    'level_stdv FLOAT(25,17) NOT NULL',
    'sd_mean FLOAT(25,17) NOT NULL',
    'sd_stdv FLOAT(25,17) NOT NULL',
    'weight FLOAT(25,17) NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

#######################################################

def create_mincontrol_interaction_table(tablename, cursor):
    fields=(
     'job_index INT NOT NULL AUTO_INCREMENT, PRIMARY KEY (job_index)',
    'instruction MEDIUMTEXT NOT NULL',
    'target MEDIUMTEXT NOT NULL',
    'param1 MEDIUMTEXT',
    'param2 MEDIUMTEXT',
    'complete INT NOT NULL')
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)


def create_mincontrol_messages_table(tablename, cursor):
    fields=(
    "message_index INT NOT NULL AUTO_INCREMENT, PRIMARY KEY (message_index)",
    "message MEDIUMTEXT NOT NULL",
    "target MEDIUMTEXT NOT NULL",
    "param1 MEDIUMTEXT",
    "param2 MEDIUMTEXT",
    "complete INT NOT NULL")
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

def create_mincontrol_barcode_control_table(tablename, cursor):
    fields=(
    "job_index INT NOT NULL AUTO_INCREMENT, PRIMARY KEY (job_index)",
    "barcodeid MEDIUMTEXT NOT NULL",
    "complete INT NOT NULL")
    colheaders=','.join(fields)
    sql ="CREATE TABLE %s (%s) ENGINE=InnoDB" % (tablename, colheaders)
    #print sql
    cursor.execute(sql)

#######################################################

def load_ref_kmer_hash(tablename, kmers, refid, cursor):
    sql="INSERT INTO %s (kmer, refid, count, total, freq) VALUES " % (tablename)
    totalkmercount = sum(kmers.itervalues())
    for kmer, count in kmers.iteritems():
        #n+=1
        f= 1 / (totalkmercount * float(count))
        freq ="{:.10f}".format(f)
        #print f, freq, totalkmercount, count
        sql+= "('%s',%s,%s,%s,%s)," % (kmer, refid, count, totalkmercount, freq)
    sql=sql[:-1]
    #print sql
    cursor.execute(sql)
    db.commit()

######################################################

def kmer_count_fasta(seq, revcompseq, kmer_len):
    kmerhash =dict()
    seqs = [seq, revcompseq]
    for x in range(len(seq)+1-kmer_len):
        for s in seqs:
            kmer = str(s[x:x+kmer_len])
            if kmer in kmerhash:
                kmerhash[kmer]+=1
            else:
                kmerhash[kmer]=1
    return kmerhash

######################################################

class MyHandler(FileSystemEventHandler):
    def __init__(self):
        self.creates=file_dict_of_folder(args.watchdir)
        self.processed=dict()
        self.running = True

        t = threading.Thread(target=self.processfiles)
        t.daemon = True
        try:
            t.start()
        except (KeyboardInterrupt, SystemExit):
            t.stop()

    def processfiles(self):
        everyten=0
        #if (args.timeout_true is not None):
        #    timeout=args.timeout_true
        while self.running:
            time.sleep(5)
            ts = time.time()
            print datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'), "CACHED:", len(self.creates), "PROCESSED:",  len(self.processed)
            for fast5file, createtime in sorted(self.creates.items(), key=lambda x: x[1]):
                #tn=time.time()
                if ( int(createtime)+20 < time.time() ): # file created 20 sec ago, so should be complete
                    if (fast5file not in self.processed.keys() ):
                        self.creates.pop(fast5file, None)
                        self.processed[fast5file]=time.time()
                        try:
                            #starttime = time.time()
                            self.hdf = h5py.File(fast5file, 'r')
                            self.db_name=check_read(fast5file, self.hdf, cursor)
                            process_fast5(fast5file, self.hdf, self.db_name, cursor)

                        except Exception, err:
                            err_string="Error with fast5 file: %s : %s" % (fast5file, err)
                            print >>sys.stderr, err_string
                        #    if (dbname is not None):
                        #        if (dbname in dbcheckhash["dbname"]):
                        #            with open(dbcheckhash["logfile"][dbname],"a") as logfilehandle:
                        #                logfilehandle.write(err_string+os.linesep)
                        #                logfilehandle.close()
                        everyten+=1
                        if (everyten==10):
                            tm = time.time()
                            if ( (ts+5)<tm ): # just to stop it printing two status messages one after the other.
                                print  datetime.datetime.fromtimestamp(tm).strftime('%Y-%m-%d %H:%M:%S'), "CACHED:", len(self.creates), "PROCESSED:",  len(self.processed)
                            everyten=0

    def on_created(self, event):
        if ("downloads" in event.src_path and "muxscan" not in event.src_path and event.src_path.endswith(".fast5")):
            self.creates[event.src_path] = time.time()

#########################################################

if __name__ == "__main__":
    if (args.version==True): # ML
        print "minUP version is "+minup_version # ML
        sys.exit() # ML
    try:
        db = MySQLdb.connect(host=args.dbhost, user=args.dbusername, passwd=args.dbpass, port=args.dbport)
        cursor = db.cursor()

    except Exception, err:
        print >>sys.stderr, "Can't connect to MySQL: %s" % (err)
        sys.exit(1)

    if ( (args.ref_fasta is not False) and (args.batch_fasta is not False) ):
        print "Both --align-ref-fasta (-f) and --align-batch-fasta (-b) were set. Select only one and try again."
        sys.exit(1)

    if ( (args.last_align is not False) and (args.bwa_align is not False) ):
        print "Both --last-align-true (-last) and --bwa-align-true (-bwa) were set. Select only one and try again."
        sys.exit(1)

    if (args.ref_fasta is not False):
        process_ref_fasta(args.ref_fasta)

    comments['default']='No Comment'
    if (args.added_comment is not ''): # MS
        comments['default']=' '.join(args.added_comment) # MS
    if (args.add_comment is True):
        comment=raw_input("Type comment then press Enter to continue : ")
        comments['default']=comment

    print "monitor started."
    try:
        event_handler = MyHandler()
        observer = Observer()
        observer.schedule(event_handler, path=args.watchdir, recursive=True)
        observer.start()
        while True:
            time.sleep(1)

    except (KeyboardInterrupt, SystemExit):
        print "stopping monitor."
        observer.stop()
        time.sleep(1)
        #if (dbname is not None):
        #    #print "dbname", dbname
        for name in dbcheckhash["dbname"].keys():
            dba = MySQLdb.connect(host=args.dbhost, user=args.dbusername, passwd=args.dbpass, port=args.dbport, db=name)
            cur = dba.cursor()
            print "setting %s to an inactive run" % (name)
            sql = "UPDATE Gru.minIONruns SET activeflag='0' WHERE runname=\"%s\" " % (name)
            cur.execute(sql)
            dba.commit()

            runindex =dbcheckhash["runindex"][name]
            finish_time=time.strftime('%Y-%m-%d %H:%M:%S')
            comment_string = "minUp version %s finished" % (minup_version)
            sql= "INSERT INTO Gru.comments (runindex,runname,user_name,comment,name,date) VALUES (%s,'%s','%s','%s','%s','%s') " % (runindex,name,args.minotourusername,comment_string,args.dbusername,finish_time)
            cur.execute(sql)
            dba.commit()

            with open(dbcheckhash["logfile"][name],"a") as logfilehandle:
                logfilehandle.write("minup finished at:\t%s:\tset to inactive gracefully%s" % (finish_time, os.linesep) )
                logfilehandle.close()
            dba.close()

        print "finished."
        sys.exit(1)
    observer.join()
    sys.exit(1)

######################################################

