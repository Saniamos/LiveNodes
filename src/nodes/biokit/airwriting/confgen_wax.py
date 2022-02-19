import sys
from . import db
import string
from . import crossval
from sqlalchemy import and_
import argparse



def retrieve_datasets(session, basename):
    """
    Retrieves the folds of a cross validation given by the name of the set.
    
    In order to find the datasets, the name must comply with a specific format,
    which is: basename_[test|train]set_fold_<crossvalidation keyval>. 
    """
    testsets = session.query(db.Dataset).\
                filter(db.Dataset.name.like(basename+"_testset_%")).\
                order_by(db.Dataset.name).all()
    trainsets = session.query(db.Dataset).\
                filter(db.Dataset.name.like(basename+"_trainset_%")).\
                order_by(db.Dataset.name).all()
    assert(len(testsets) == len(trainsets))
    sets = list(zip(trainsets, testsets))
    nrfolds = len(sets)
    for set in sets:
        yield {'trainset': set[0], 'testset': set[1],
               'keyval': set[0].name[-3:], 'nrfolds': nrfolds}
        
    
parser = argparse.ArgumentParser(description="Create a configuration for "+
                                 "wax cross validation")
parser.add_argument('database', help="sqlite database file to use")
args = parser.parse_args()

airdb = db.AirDb(args.database)


#Configuration to use

pp = db.get_or_create(airdb.session, db.PreProStandard,
    windowsize = 10,
    frameshift = 10,
    filterstring = "",
    channels = "2 3 4 5 6 7",
    meansub = "",
    feature = "ADC",
    janus_desc = "/project/AMR/Handwriting/flat/featDesc.adis.02.tcl",
    janus_access = "/project/AMR/Handwriting/flat/featAccess.adis.01.tcl",
    biokit_desc = "stdprepro")

cmtype = db.get_or_create(airdb.session, db.ContextModelType,
    name = "grammar")
cm = db.get_or_create(airdb.session, db.ContextModel,
    name="grammar_alphabet",
    file="/project/AMR/Handwriting/flat/grammar_alphabet.nav",
    type=cmtype)

dictionary = db.get_or_create(airdb.session, db.Dictionary,
    name = "dict_alphabet",
    file = "/project/AMR/Handwriting/flat/dict_alphabet")

vocabulary = db.get_or_create(airdb.session, db.Vocabulary,
    name = "vocab_alphabet",
    file = "/project/AMR/Handwriting/flat/vocab_alphabet")


cmtype_ngram = db.get_or_create(airdb.session, db.ContextModelType,
    name = "ngram")

cm_ngram8k = db.get_or_create(airdb.session, db.ContextModel,
    name="lm_en_3gram_8k",
    file="/project/AMR/Handwriting/lm/English.vocab.en.10k.merg.sel_v2.lm",
    type=cmtype_ngram)

dictionary8k = db.get_or_create(airdb.session, db.Dictionary,
    name = "dict_en_8k_norepos",
    file = "/project/AMR/Handwriting/vocab/dict.en.10k.merg.norepos.sel_v2")

vocabulary8k = db.get_or_create(airdb.session, db.Vocabulary,
    name = "vocab_en_8k_norepos",
    file = "/project/AMR/Handwriting/vocab/vocab.en.10k.merg.norepos.sel_v2")


atomset = db.get_or_create(airdb.session, db.AtomSet,
    name = "alphabet",
    enumeration = (" ".join(string.lowercase)))

topology = db.get_or_create(airdb.session, db.TopologyConfig, 
    hmmstates = 30,
    hmm_repos_states = 10,
    gmm = 6,
    gmm_repos = 2)

ibis = db.get_or_create(airdb.session, db.IbisConfig,
    wordPen = 50,
    lz = 60,
    wordBeam = 500,
    stateBeam = 500,
    morphBeam = 500)

biokit = db.get_or_create(airdb.session, db.BiokitConfig,
    token_insertion_penalty = 50,
    tokensequencemodel_weight = 60,
    hypo_topn = 5,
    hypo_beam = 10,
    final_node_topn = 300,
    final_node_beam = 100,
    active_node_topn = 15000,
    active_node_beam = 600)

#trainset = airdb.session.query(db.Dataset).filter(
#    db.Dataset.name=="character_rh_rp_all").one()
#find appropriate base models
# use hardcoded cross validation id = 5
#basecv = airdb.session.query(db.CrossValidation).\
#            filter(db.CrossValidation.id == 5).one()

sen_trainset = airdb.session.query(db.Dataset).\
                        filter(db.Dataset.name == "set_all_sentences").one()
#check for existing models
print("Looking for basemodel:")
sentence_iterations = 3
configs = airdb.session.query(db.Configuration).\
                       filter(and_(
                         db.Configuration.data_basedir == "/project/AMR/Handwriting/data",
                         db.Configuration.janusdb_name == '/project/AMR/Handwriting/data/db/db_sentences',
                         db.Configuration.atomset == atomset,
                         db.Configuration.preprocessing == pp,
                         db.Configuration.topology == topology,
                         db.Configuration.transcriptkey == "reference",
                         db.Configuration.trainset == sen_trainset)).all()
print("done")
if len(configs) == 0:
    print("No existing basemodel config found, cannot create config")
    sys.exit(0)
elif len(configs) == 1:
    print(("Found existing config: %s" % configs[0].id))
    print("Retrive base model")
    basemodel = airdb.session.query(db.ModelParameters).\
        filter(db.ModelParameters.configuration_id == configs[0].id).\
        filter(db.ModelParameters.iteration == sentence_iterations).one()
    print("done")
else:
    print(("Found %s configurations matching the query:" % (len(configs), )))
    print(configs)
    print("Multiple base configs found, this should not happen")
    sys.exit(0)


print("Generating folds")
cvfoldgenerator = retrieve_datasets(airdb.session, "wax_cv_no72")
cvconfigs = []
for fold in cvfoldgenerator:
    train_ids = [x.id for x in fold['trainset'].recordings]
    test_ids = [x.id for x in fold['testset'].recordings]
    print("create fold config")
    config = db.get_or_create(airdb.session, db.Configuration,
        data_basedir = "/project/AMR/Handwriting/data",
        janusdb_name = "/project/AMR/Handwriting/data/db/waxtest",
        atomset = atomset,
        vocabulary = vocabulary8k,
        dictionary = dictionary8k,
        contextmodel = cm_ngram8k,
        preprocessing = pp,
        topology = topology,
        biokitconfig = biokit,
        ibisconfig = None,
        iterations = 5,
        basemodel = basemodel,
        transcriptkey = "reference",
        trainset = fold['trainset'],
        testset = fold['testset'])
    print("done")
    
    cvconfigs.append(config)
    

#only create a new cross-validation if necessary
    
print("Create CrossValidation")
cv_is_new = True
cvs = airdb.session.query(db.CrossValidation).all()
for cv in cvs:
    if sorted(list(cv.configurations)) == sorted(cvconfigs):
        print("Cross Validation with given configs already exists")
        cv_is_new = False
        break
if cv_is_new:
    print("Create new Cross Validation")
    crossvalidation = db.CrossValidation()
    crossvalidation.nr_folds = len(cvconfigs)
    crossvalidation.configurations = cvconfigs
    airdb.session.add(crossvalidation)
    airdb.session.commit()
print("done")

print("Adding jobs")
for config in cvconfigs:
    if not config.jobs:
        #alright no job associated with the config, let's create one
        job = db.Job(configuration = config, status = "waiting")
        print(("Adding job with configuration id: %s" % (job.configuration.id, )))
        airdb.session.add(job)
        airdb.session.commit()
print("done")