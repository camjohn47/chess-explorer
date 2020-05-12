from glob import glob
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
import numpy as np
import random 
import chess
import chess.pgn
import math
import pickle

# A pipeline for parsing, analyzing and modeling large amounts of chess data. The data must be expressed in pgn format. 
class ChessPipeline():

	# "pgn_directory" is the directory in which pgn files containing chess game data are located. Pgn is a format used to represent chess games, and a pgn file contains chess games represented in pgn format.
	#  The pipeline possesses a SGDClassifier model, which can be trained to classify chess positions using ML.
	def __init__(self,pgn_directory,model_args=None):
		self.pgn_directory = pgn_directory
		self.pgn_paths = glob(pgn_directory + '/*')
		self.num_pgns = len(self.pgn_paths)
		self.model = SGDClassifier(**model_args)

		# Five major piece types for each player--excluding kings--where white's pieces are capitalized and black's are in lower-case.
		self.white_pieces = ['P', 'N', 'B', 'R', 'Q']
		self.black_pieces = ['p', 'n', 'b', 'r', 'q']
		self.piece_indices = range(1,7)

	# Determine whether a game's data meets cleanliness criteria. Used in preprocessing to build training data. 
	def headers_filter(self,headers):
		if not headers:
			return False

		elif "Date" not in headers or headers["Result"][0] == '*' or '2' in headers["Result"]:
			return False

		else:
			return True

	# Create a hash key for a game using its headers. Specifically, a game is hashed using its date and both players. This means that games are uniquely represented unless 
	# they were played on the same date and by the same two players. 
	def hash_game(self,game):
		hash_features = []
		headers = game.headers
		hash_features.append(headers['Date'])
		hash_features.append(headers['Black'])
		hash_features.append(headers['White'])
		game_hash = ' '.join(hash_features)

		return game_hash

	# Randomly partitions the raw chess position data found in its pgn files. This partitioning is used to prepare mini-batches, which are used for training the classification model.
	# We partition the raw data before building features to prevent memory overflow. Even simple features are too large to be held in memory for > 10,000's of games together (for most computers). 
	def partition_pgn_data(self,num_partitions,downsample):
		partitions = [ [] for partition in range(num_partitions)]
		game_index = 0
		for pgn_path in self.pgn_paths:

			if game_index > downsample:
				break

			pgn = open(pgn_path,encoding="latin-1")
			game = chess.pgn.read_game(pgn)

			while game:

				if self.headers_filter(game.headers):
					game_hash = self.hash_game(game)
					partition = hash(game_hash) % num_partitions
					partitions[partition].append(game)
					game_index += 1

				if game_index % 1000 == 0:
					print(game_index)

				if game_index > downsample:
					break

				game = chess.pgn.read_game(pgn)

		return partitions

	# Count the number of all 12 piece types on the board. There are 6 pieces for each side (white and black): pawn,knight,bishop,rook,queen,king, which are defined in that order and with white chosen first. 
	def get_piece_counts(self,board):
		piece_counts = []
		for piece_index in self.piece_indices:
			piece_squares = board.pieces(piece_index, True)
			piece_count = len(piece_squares)
			piece_counts.append(piece_count)

		for piece_index in self.piece_indices:
			piece_squares = board.pieces(piece_index, False)
			piece_count = len(piece_squares)
			piece_counts.append(piece_count)

		return piece_counts

	def count_bishop_pairs(self,piece_counts):
		white_bishop_pair = 0

		if piece_counts[2] == 2:
			white_bishop_pair = 1

		black_bishop_pair = 0
		
		if piece_counts[8] == 2:
			black_bishop_pair = 1

		return [white_bishop_pair,black_bishop_pair]

	# Build input features for a chess board that will be considered in the model. 
	def get_features(self,board):
		piece_counts = self.get_piece_counts(board)
		white_mobility,black_mobility = self.get_mobility(board)
		white_bishop_pair,black_bishop_pair = self.count_bishop_pairs(piece_counts)
		postitional_features = [white_mobility,black_mobility]
		features = piece_counts + postitional_features

		return features

	def get_mobility(self,board):
		white_mobility,black_mobility = 0,0
		null = chess.Move.null()

		if board.turn:
			white_mobility = board.legal_moves.count()
			board.push(null)
			black_mobility = board.legal_moves.count()
			board.pop()

		else:
			black_mobility = board.legal_moves.count()
			board.push(null)
			white_mobility = board.legal_moves.count()
			board.pop()

		return [white_mobility,black_mobility]

	def get_active_squares(self,board):
		active_squares = []
		for piece_index in self.piece_indices:
			white_squares = board.pieces(piece_index + 1, True)
			for square in white_squares:
				active_square = (64*piece_index) + square
				active_squares.append(active_square)

		for piece_index in self.piece_indices:
			black_squares = board.pieces(piece_index + 1, False)
			for square in black_squares:
				active_square = (64*piece_index) + square
				active_squares.append(active_square)

		return active_squares

	def process_game(self,game):
		inputs = []
		outputs = []
		headers = game.headers
		result = int(float(headers["Result"][0]))
		board = game.board()

		for move in game.mainline_moves():
			board.push(move)
			board_features = self.get_features(board)
			inputs.append(board_features)
			outputs.append(result)

		return [inputs,outputs]

	def build_batch(self,games):
		transformed_inputs = []
		transformed_outputs = []

		for game in games: 
			inputs,outputs = self.process_game(game)
			transformed_inputs += inputs
			transformed_outputs += outputs
			inputs,outputs = None,None

		indices = list(range(len(transformed_inputs)))
		random.shuffle(indices)
		shuffled_inputs = [transformed_inputs[i] for i in indices]
		shuffled_outputs = [transformed_outputs[i] for i in indices]

		return [shuffled_inputs,shuffled_outputs]

	def batch_learning(self,num_partitions,model_path,downsample=None):
		partitions = self.partition_pgn_data(num_partitions,downsample)
		i = 0
		for partition in partitions:
			batch_inputs,batch_outputs = self.build_batch(partition)
			self.model.partial_fit(np.matrix(batch_inputs),batch_outputs,classes=[1,0])
			self.save_model(model_path)
			i += 1

	def save_model(self,model_path):
		model_file = open(model_path,'wb')
		pickle.dump(self.model,model_file)
		model_file.close()

	def show_piece_importance(self):
		piece_importance = {}
		feature_weights = self.model.coef_[0]

		for i,piece in self.pieces:
			importance = feature_weights[i]
			piece_importance[piece] = importance

		piece_importance = sorted(piece_importance)



		



